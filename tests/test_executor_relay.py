import asyncio
import json
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.dtest.api_service.errors import ApiError
from src.dtest.api_service.routers import executor as relay
from src.dtest.api_service.routers.executor import _match
from src.dtest.api_service.services.api_clients import Caller
from src.dtest.core.config import Settings
from src.dtest.core.executor.client import ExecutorClient

E = "674ff370-c4c6-42c4-a423-eba72d18352b"


def _access(method: str, path: str) -> tuple[Any, bool] | None:
    route = _match(method, path)
    return route[1:] if route else None


def test_browser_routes():
    assert _access("GET", "executions") == ("list", True)
    route = _match("GET", f"executions/{E}/steps")
    assert route and route[1] == "execution" and route[0]["execution"] == E
    assert _access("GET", f"executions/{E}/attempts") == ("admin", False)
    assert _access("POST", "runtime-targets") == ("ops", False)
    assert _access("POST", f"runtime-targets/{E}/drain") == ("ops", False)
    assert _access("POST", "maintenance/drain") == ("ops", False)
    assert _access("DELETE", f"runtime-targets/{E}") == ("ops", False)
    for method, path in [
        ("GET", f"executions/{E}/../../maintenance"),
        ("GET", "executions/not-a-uuid"),
        ("DELETE", f"executions/{E}"),
    ]:
        assert _match(method, path) is None


def test_key_callers_may_write_but_not_operate():
    for method, path in [
        ("POST", "executions"),
        ("POST", f"executions/{E}/operations"),
        ("POST", f"executions/{E}/finalize"),
        ("POST", f"executions/{E}/cancel"),
        ("POST", f"executions/{E}/retry"),
        ("POST", f"executions/{E}/artifacts"),
        ("GET", f"artifacts/{E}/content"),
        ("GET", f"executions/{E}/notebook/cells/3"),
    ]:
        route = _access(method, path)
        assert route is not None and route[1] is True, path
        assert route[0] is None or method == "GET"  # browser: reads only
    for path in [
        f"executions/{E}/diagnostics",
        "runtime-targets",
        "runtime-pools",
        "maintenance",
    ]:
        route = _access("GET", path)
        assert route is not None and route[1] is False


# --- forwarding ------------------------------------------------------------


def _services(
    sent: list[httpx.Request], admin_key: str = "", api_key: str = "exe_ours"
):
    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"ok": True})

    executor = ExecutorClient(
        "http://executor", 5, api_key, admin_key, "pr-agentic"
    )
    executor.http = httpx.AsyncClient(
        base_url="http://executor/api/v1",
        transport=httpx.MockTransport(handle),
    )
    return SimpleNamespace(
        settings=Settings(executor_tenant_id="pr-agentic"), executor=executor
    )


def _request(method: str, path: str, headers: dict[str, str], body=b""):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": method,
            "path": f"/api/v1/executor/{path}",
            "query_string": b"limit=5",
            "headers": [
                (k.lower().encode(), v.encode()) for k, v in headers.items()
            ],
        },
        receive,
    )


def _as_caller(services, method, path, headers, body=b"", tenant="partner"):
    caller = Caller("c-1", "partner-agent", tenant)
    user = SimpleNamespace(id="u-1", role="user")
    response = asyncio.run(
        relay._for_caller(
            cast(Any, services),
            _request(method, path, headers, body),
            path,
            caller,
            user.id,
            cast(Any, user),
        )
    )
    return response


def test_key_caller_goes_as_its_tenant_with_our_key():
    sent: list[httpx.Request] = []
    body = json.dumps({"idempotency_key": "k"}).encode()
    response = _as_caller(
        _services(sent),
        "POST",
        "executions",
        {
            "X-Api-Key": "pas_live_theirs",
            "X-Tenant-Id": "someone-else",
            "X-Project-Id": "their-project",
            "X-Session-Id": "their-session",
            "Content-Type": "application/json",
        },
        body,
    )
    assert response.status_code == 200
    headers = sent[0].headers
    assert headers["x-api-key"] == "exe_ours"
    assert headers["x-tenant-id"] == "partner"
    assert headers["x-user-id"] == "u-1"
    # another tenant's project is its own: passed on after a form check
    assert headers["x-project-id"] == "their-project"
    assert headers["x-session-id"] == "their-session"
    assert sent[0].content == body
    assert sent[0].url.params["limit"] == "5"


def test_key_caller_of_our_tenant_needs_project_membership(monkeypatch):
    async def not_member(services, user, project_id, write=False):
        raise HTTPException(404, "Project not found.")

    monkeypatch.setattr(relay, "project_for", not_member)
    with pytest.raises(HTTPException) as err:
        _as_caller(
            _services([]),
            "GET",
            "executions",
            {"X-Project-Id": "someone-elses"},
            tenant="pr-agentic",
        )
    assert err.value.status_code == 404


def test_operator_routes_need_the_operator_key():
    match = _match("GET", "runtime-targets")
    assert match is not None
    admin = cast(Any, SimpleNamespace(id="a-1", role="admin"))
    with pytest.raises(ApiError) as err:
        asyncio.run(
            relay._for_user(
                cast(Any, _services([])),
                _request("GET", "runtime-targets", {}),
                "runtime-targets",
                match,
                admin,
            )
        )
    assert err.value.status == 503
    sent: list[httpx.Request] = []
    asyncio.run(
        relay._for_user(
            cast(Any, _services(sent, admin_key="exe_ops")),
            _request("GET", "runtime-targets", {}),
            "runtime-targets",
            match,
            admin,
        )
    )
    assert sent[0].headers["x-api-key"] == "exe_ops"
    assert sent[0].headers["x-user-id"] == "a-1"
    assert "x-tenant-id" not in sent[0].headers


def test_browser_list_is_scoped_by_the_user_header(monkeypatch):
    async def member(services, user, params):
        return None

    monkeypatch.setattr(relay, "scope_execution_list", member)
    match = _match("GET", "executions")
    assert match is not None
    sent: list[httpx.Request] = []
    user = cast(Any, SimpleNamespace(id="u-9", role="user"))
    request = _request("GET", "executions", {"X-User-Id": "spoof"})
    request.scope["query_string"] = b"user_id=spoof&tenant_id=x&status=RUNNING"
    asyncio.run(
        relay._for_user(
            cast(Any, _services(sent)), request, "executions", match, user
        )
    )
    assert sent[0].headers["x-user-id"] == "u-9"
    assert dict(sent[0].url.params) == {"status": "RUNNING"}


def test_admin_user_filter_becomes_the_user_header():
    match = _match("GET", "executions")
    assert match is not None
    sent: list[httpx.Request] = []
    admin = cast(Any, SimpleNamespace(id="a-1", role="admin"))
    request = _request("GET", "executions", {})
    request.scope["query_string"] = b"user_id=U-7&trigger_type=INTERACTIVE"
    asyncio.run(
        relay._for_user(
            cast(Any, _services(sent)), request, "executions", match, admin
        )
    )
    assert sent[0].headers["x-user-id"] == "u-7"
    assert dict(sent[0].url.params) == {"trigger_type": "INTERACTIVE"}


def test_relay_docs_list_the_key_routes():
    text = relay.relay_description()
    keyed = text.split("made for `X-User-Id`:")[1].split("Runtime,")[0]
    assert "| POST | `/executions` |" in keyed
    assert "| GET | `/executions/{execution_id}/steps/{id}` |" in keyed
    assert "`/executions/{execution_id}/notebook/cells/{n}`" in keyed
    for internal in ("attempts", "diagnostics", "runtime-", "maintenance"):
        assert internal not in keyed


def _operator_post(path: str, body: bytes) -> httpx.Request:
    match = _match("POST", path)
    assert match is not None
    admin = cast(Any, SimpleNamespace(id="a-1", role="admin"))
    sent: list[httpx.Request] = []
    asyncio.run(
        relay._for_user(
            cast(Any, _services(sent, admin_key="exe_ops")),
            _request("POST", path, {}, body),
            path,
            match,
            admin,
        )
    )
    return sent[0]


def test_operator_writes_go_unchanged_as_the_admin():
    body = json.dumps({"idempotency_key": "k", "name": "x"}).encode()
    sent = _operator_post("runtime-targets", body)
    # the executor records the admin from X-User-Id; the body is theirs
    assert sent.content == body
    assert sent.headers["x-user-id"] == "a-1"
    assert sent.headers["x-api-key"] == "exe_ops"


def test_operator_post_without_a_body_sends_none():
    sent = _operator_post(f"runtime-targets/{E}/probe", b"")
    assert sent.content == b""
    assert "content-type" not in sent.headers


# --- standard (일반) and master (마스터) keys -----------------------------


def _keyed_read(kind: str, query: bytes, method: str = "GET"):
    sent: list[httpx.Request] = []
    services = _services(sent)
    request = _request(method, "executions", {"X-Api-Key": "pas_live_x"})
    request.scope["query_string"] = query
    caller = Caller("c-1", "partner-agent", "partner", kind)
    asyncio.run(
        relay._for_caller(
            cast(Any, services), request, "executions", caller, "e100", None
        )
    )
    return sent[0]


def test_standard_key_reads_only_its_users_own():
    sent = _keyed_read("standard", b"status=RUNNING&tenant_id=x")
    assert sent.headers["x-user-id"] == "e100"
    assert dict(sent.url.params) == {"status": "RUNNING"}
    # naming the same user is allowed (and needs no filter)
    sent = _keyed_read("standard", b"user_id=E100")
    assert sent.headers["x-user-id"] == "e100"
    assert "user_id" not in sent.url.params


def test_standard_key_may_not_filter_by_another_user():
    with pytest.raises(ApiError) as err:
        _keyed_read("standard", b"user_id=e200")
    assert (err.value.status, err.value.code) == (403, "FORBIDDEN")


def test_master_key_reads_the_tenant_and_filters_by_query():
    sent = _keyed_read("master", b"status=RUNNING")
    assert "x-user-id" not in sent.headers
    assert sent.headers["x-tenant-id"] == "partner"
    assert dict(sent.url.params) == {"status": "RUNNING"}
    sent = _keyed_read("master", b"user_id=E200")
    assert "x-user-id" not in sent.headers
    assert sent.url.params["user_id"] == "e200"


def test_writes_go_for_the_caller_whatever_the_key():
    for kind in ("standard", "master"):
        sent = _keyed_read(kind, b"user_id=e200", method="POST")
        assert sent.headers["x-user-id"] == "e100"
        assert "user_id" not in sent.url.params


def test_malformed_user_filter_is_refused():
    with pytest.raises(ApiError) as err:
        _keyed_read("master", b"user_id=Bad%20Id")
    assert (err.value.status, err.value.code) == (400, "INVALID_IDENTITY")


def _admin_read(path: str, query: bytes, role: str = "admin"):
    match = _match("GET", path)
    assert match is not None
    sent: list[httpx.Request] = []
    user = cast(Any, SimpleNamespace(id="a-1", role=role))
    request = _request("GET", path, {})
    request.scope["query_string"] = query
    asyncio.run(
        relay._for_user(cast(Any, _services(sent)), request, path, match, user)
    )
    return sent[0]


def test_admin_reads_another_tenant_by_query():
    sent = _admin_read("executions", b"tenant_id=partner-a&status=QUEUED")
    assert sent.headers["x-tenant-id"] == "partner-a"
    assert sent.headers["x-api-key"] == "exe_ours"
    assert dict(sent.url.params) == {"status": "QUEUED"}
    for path in (f"executions/{E}", f"executions/{E}/attempts"):
        assert (
            _admin_read(path, b"tenant_id=partner-a").headers["x-tenant-id"]
            == "partner-a"
        )
    # without it: our own tenant
    ours = _admin_read("executions", b"")
    assert ours.headers["x-tenant-id"] == "pr-agentic"


def test_tenant_query_is_checked_and_admin_only(monkeypatch):
    for bad in (b"tenant_id=Bad_Tenant", b"tenant_id=dlq"):
        with pytest.raises(HTTPException) as err:
            _admin_read("executions", bad)
        assert err.value.status_code == 422

    async def member(services, user, params):
        return None

    monkeypatch.setattr(relay, "scope_execution_list", member)
    sent = _admin_read("executions", b"tenant_id=partner-a", role="user")
    assert sent.headers["x-tenant-id"] == "pr-agentic"
