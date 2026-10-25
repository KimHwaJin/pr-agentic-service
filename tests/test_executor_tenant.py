import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from pydantic import ValidationError

from agent.tools import analysis
from api_service.routers.batch import sets_tenant, with_tenant
from core.config import Settings
from core.executor.client import ExecutorClient, ExecutorError
from worker import executor_events


def test_events_come_from_the_tenant_stream():
    settings = Settings(executor_tenant_id="pr-agentic")
    assert settings.executor_tenant_stream == "executor.events.pr-agentic"


@pytest.mark.parametrize("tenant", ["dlq", "work", "Pr", "a", "ab-", "1ab"])
def test_tenant_must_be_a_valid_unreserved_name(tenant):
    with pytest.raises(ValidationError):
        Settings(executor_tenant_id=tenant)


def _client(tenant_id: str, sent: list[dict[str, Any]]):
    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(202, json={"execution_id": "x-1"})

    client = ExecutorClient("http://executor", 5, tenant_id)
    client.http = httpx.AsyncClient(
        base_url="http://executor/api/v1",
        transport=httpx.MockTransport(handle),
    )
    return client


def _submit(client: ExecutorClient):
    return asyncio.run(
        client.submit(
            idempotency_key="k",
            context={"user_id": "u-1"},
            steps=[],
            profile="default",
            wait_seconds=600,
        )
    )


def test_submission_carries_the_tenant_at_the_top_level():
    sent: list[dict[str, Any]] = []
    _submit(_client("pr-agentic", sent))
    assert sent[0]["tenant_id"] == "pr-agentic"
    assert "tenant_id" not in sent[0]["context"]


def test_executor_error_code():
    body = {"error": {"code": "EXECUTION_VERSION_CONFLICT", "message": "m"}}
    assert ExecutorError(409, body).code == "EXECUTION_VERSION_CONFLICT"
    assert ExecutorError(502, "bad gateway").code is None


def test_notebook_is_read_in_full_for_its_path():
    asked: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        if request.url.path.endswith("/artifacts"):
            items = [
                {"artifact_id": "r-1", "type": "REPORT", "storage": {}},
                {"artifact_id": "nb-1", "type": "NOTEBOOK", "storage": {}},
            ]
            return httpx.Response(200, json={"items": items})
        return httpx.Response(
            200,
            json={
                "artifact_id": "nb-1",
                "type": "NOTEBOOK",
                "storage": {"relative_path": "users/u/run.ipynb"},
            },
        )

    client = ExecutorClient("http://executor", 5, "pr-agentic")
    client.http = httpx.AsyncClient(
        base_url="http://executor/api/v1",
        transport=httpx.MockTransport(handle),
    )
    notebook = asyncio.run(client.notebook("x-1"))
    assert notebook and notebook["storage"]["relative_path"] == (
        "users/u/run.ipynb"
    )
    assert asked == [
        "/api/v1/executions/x-1/artifacts",
        "/api/v1/artifacts/nb-1",
    ]


def test_executions_are_read_until_they_pass_the_cutoff():
    pages = {
        None: {
            "items": [
                {"execution_id": "a", "created_at": "2026-10-25T10:00:00Z"},
                {"execution_id": "b", "created_at": "2026-10-24T10:00:00Z"},
            ],
            "next_cursor": "c-2",
        },
        "c-2": {
            "items": [
                {"execution_id": "c", "created_at": "2026-10-23T10:00:00Z"},
                {"execution_id": "d", "created_at": "2026-10-10T10:00:00Z"},
            ],
            "next_cursor": "c-3",
        },
    }
    asked: list[dict[str, str]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        asked.append(params)
        return httpx.Response(200, json=pages[params.get("cursor")])

    client = ExecutorClient("http://executor", 5, "pr-agentic")
    client.http = httpx.AsyncClient(
        base_url="http://executor/api/v1",
        transport=httpx.MockTransport(handle),
    )
    cutoff = datetime(2026, 10, 20, tzinfo=UTC)
    found = asyncio.run(client.executions(cutoff, trigger_type="BATCH"))
    assert [e["execution_id"] for e in found] == ["a", "b", "c"]
    assert len(asked) == 2  # c-3 is never asked for
    assert asked[0] == {"trigger_type": "BATCH", "limit": "200"}


def test_batch_registration_names_our_tenant():
    body = with_tenant(
        b'{"name": "daily", "tenant_id": "other"}', "pr-agentic"
    )
    assert json.loads(body) == {"name": "daily", "tenant_id": "pr-agentic"}
    assert with_tenant(b"not json", "pr-agentic") == b"not json"
    assert with_tenant(b"[1]", "pr-agentic") == b"[1]"


def test_batch_edit_names_our_tenant_only_when_it_sends_one():
    body = with_tenant(b'{"tenant_id": "other"}', "pr-agentic", edit=True)
    assert json.loads(body) == {"tenant_id": "pr-agentic"}
    name_only = b'{"name": "daily"}'
    assert with_tenant(name_only, "pr-agentic", edit=True) == name_only


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("POST", "batches", True),
        ("POST", "/batches/", True),
        ("PATCH", "batches/b-1", True),
        ("PATCH", "batches", False),
        ("POST", "batches/b-1/runs", False),
        ("POST", "batches/b-1/enable", False),
        ("PATCH", "scripts/s-1", False),
        ("GET", "batches/b-1", False),
    ],
)
def test_registration_and_edit_name_our_tenant(method, path, expected):
    assert sets_tenant(method, path) is expected


# --- consumer --------------------------------------------------------------


class FakeRedis:
    def __init__(self):
        self.groups: list[tuple[str, str]] = []
        self.acked: list[tuple[str, str]] = []

    async def xgroup_create(self, stream, group, id, mkstream):
        assert mkstream
        self.groups.append((stream, id))

    async def xack(self, stream, group, message_id):
        self.acked.append((stream, message_id))


def _consumer(redis, progress):
    async def on_progress(execution_id, event):
        progress.append(event["event_type"])

    return executor_events.ExecutorEventConsumer(
        cast(Any, None),
        cast(Any, redis),
        "executor.events.pr-agentic",
        "g",
        "c",
        on_wake=None,
        on_progress=on_progress,
        on_completed=None,
    )


def test_group_starts_at_the_oldest_entry():
    redis = FakeRedis()
    asyncio.run(_consumer(redis, [])._create_group())
    assert redis.groups == [("executor.events.pr-agentic", "0")]


def test_handover_events_are_progress():
    redis, progress = FakeRedis(), []
    fields = {
        "event_id": "e1",
        "execution_id": "x-1",
        "event_type": "execution.step_handover_started",
        "event_sequence": "4",
        "payload": '{"status":"RUNNING","reason":"EXECUTOR_SHUTDOWN"}',
        "tenant_id": "pr-agentic",
    }
    consumer = _consumer(redis, progress)
    asyncio.run(consumer._handle("m1", fields))
    assert progress == ["execution.step_handover_started"]
    assert redis.acked == [("executor.events.pr-agentic", "m1")]


# --- next operation of a live execution ----------------------------------


class FakeExecutor:
    def __init__(self, errors, state=None):
        self.errors, self.state, self.calls = list(errors), state, []

    async def append_operation(self, execution_id, **kwargs):
        self.calls.append(kwargs)
        if self.errors:
            raise self.errors.pop(0)
        return {"operation": {"operation_id": "op"}}

    async def get(self, execution_id):
        return {"state": self.state}


def _error(status, code):
    return ExecutorError(status, {"error": {"code": code, "message": "m"}})


def _append(executor):
    runtime = SimpleNamespace(
        context=SimpleNamespace(
            run_id="run", services=SimpleNamespace(executor=executor)
        ),
        tool_call_id="call",
    )
    execution = {"id": "x-1", "version": 3}
    return asyncio.run(
        analysis._append(cast(Any, runtime), execution, [{"sequence": 5}])
    )


def test_stale_version_is_read_again_and_keeps_the_kernel():
    executor = FakeExecutor(
        [_error(409, "EXECUTION_VERSION_CONFLICT")],
        state={"status": "WAITING_FOR_OPERATION", "version": 4},
    )
    assert _append(executor) is not None
    assert [c["expected_version"] for c in executor.calls] == [3, 4]
    keys = [c["idempotency_key"] for c in executor.calls]
    assert keys[0] != keys[1]


def test_stale_version_of_a_closed_execution_starts_over():
    executor = FakeExecutor(
        [_error(409, "EXECUTION_VERSION_CONFLICT")],
        state={"status": "FAILED", "version": 9},
    )
    assert _append(executor) is None


def test_persistence_conflict_repeats_the_same_request():
    executor = FakeExecutor([_error(409, "PERSISTENCE_CONFLICT")])
    assert _append(executor) is not None
    first, second = executor.calls
    assert first == second


@pytest.mark.parametrize(
    ("status", "code"),
    [(409, "INVALID_STATE_TRANSITION"), (404, "EXECUTION_NOT_FOUND")],
)
def test_execution_that_takes_no_more_operations_starts_over(status, code):
    assert _append(FakeExecutor([_error(status, code)])) is None


def test_idempotency_conflict_is_not_hidden():
    with pytest.raises(ExecutorError):
        _append(FakeExecutor([_error(409, "IDEMPOTENCY_CONFLICT")]))
