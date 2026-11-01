from typing import Any, cast

import pytest

from src.dtest.worker.executor_events import matches


def test_operation_wait_matches_only_its_operation():
    waiting = {"operation_id": "op-1"}
    assert matches(
        waiting, "execution.operation_completed", {"operation": {"id": "op-1"}}
    )
    assert not matches(
        waiting, "execution.operation_completed", {"operation": {"id": "op-2"}}
    )
    assert matches(
        waiting, "execution.completed", {}
    )  # terminal execution always ends the wait


def test_finalize_wait_matches_completion_only():
    waiting = {"operation_id": None}
    assert not matches(
        waiting, "execution.operation_completed", {"operation": {"id": "x"}}
    )
    assert matches(waiting, "execution.completed", {"status": "SUCCEEDED"})


def test_recovery_delivers_the_event_the_run_waits_for(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from src.dtest.worker import executor_events

    delivered = []

    async def deliver(db, event):
        delivered.append(event)
        return "run-1"

    class Executor:
        async def events(self, execution_id, after_sequence=None):
            return [
                {
                    "event_id": "e1",
                    "event_sequence": 1,
                    "event_type": "execution.step_completed",
                    "payload": {},
                },
                {
                    "event_id": "e2",
                    "event_sequence": 2,
                    "event_type": "execution.operation_completed",
                    "payload": {"operation": {"id": "other"}},
                },
                {
                    "event_id": "e3",
                    "event_sequence": 3,
                    "event_type": "execution.operation_completed",
                    "payload": {"operation": {"id": "op-1"}},
                },
            ]

    monkeypatch.setattr(executor_events, "deliver", deliver)
    recovery = executor_events.MissedEventRecovery(
        cast(Any, None), cast(Any, Executor()), on_wake=None, after_seconds=120
    )
    run = cast(
        Any,
        SimpleNamespace(
            id="run-1", waiting={"execution_id": "x-1", "operation_id": "op-1"}
        ),
    )
    assert asyncio.run(recovery._recover(run)) == "run-1"
    assert [e["event_id"] for e in delivered] == ["e3"]
    assert delivered[0]["execution_id"] == "x-1"


def test_recovery_leaves_runs_whose_event_has_not_happened(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from src.dtest.worker import executor_events

    class Executor:
        async def events(self, execution_id, after_sequence=None):
            return [
                {
                    "event_id": "e1",
                    "event_sequence": 1,
                    "event_type": "execution.step_completed",
                    "payload": {},
                }
            ]

    recovery = executor_events.MissedEventRecovery(
        cast(Any, None), cast(Any, Executor()), on_wake=None, after_seconds=120
    )
    run = cast(
        Any,
        SimpleNamespace(
            id="run-1", waiting={"execution_id": "x-1", "operation_id": "op-1"}
        ),
    )
    assert asyncio.run(recovery._recover(run)) is None


def test_recovery_checks_least_recently_checked_waits_with_backoff():
    import asyncio
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from sqlalchemy.dialects import postgresql

    from src.dtest.worker import executor_events

    statements: list[str] = []
    run = SimpleNamespace(id="run-1", waiting={})

    class Session:
        async def scalars(self, statement):
            statements.append(
                str(statement.compile(dialect=postgresql.dialect()))
            )
            return SimpleNamespace(all=lambda: [run])

        async def execute(self, statement):
            statements.append(
                str(statement.compile(dialect=postgresql.dialect()))
            )

        async def commit(self):
            pass

    class Db:
        @asynccontextmanager
        async def sessions(self):
            yield Session()

    recovery = executor_events.MissedEventRecovery(
        cast(Any, Db()), cast(Any, None), on_wake=None, after_seconds=120
    )
    assert asyncio.run(recovery.sweep()) == []  # no execution id: skipped
    select_sql, update_sql = statements
    assert "ORDER BY runs.recovery_checked_at ASC NULLS FIRST" in select_sql
    assert "CASE WHEN" in select_sql
    assert "recovery_checked_at=" in update_sql
    assert "updated_at=runs.updated_at" in update_sql


def _timeline_client(sent, items):
    import httpx

    from src.dtest.core.executor.client import ExecutorClient

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(dict(request.url.params))
        return httpx.Response(200, json={"items": items})

    client = ExecutorClient("http://executor", 5, "k", "", "pr-agentic")
    client.http = httpx.AsyncClient(
        base_url="http://executor/api/v1",
        transport=httpx.MockTransport(handle),
    )
    return client


def test_confirming_an_event_reads_only_that_event():
    import asyncio

    sent: list[dict] = []
    item = {"event_id": "e9", "event_sequence": 9, "event_type": "x"}
    client = _timeline_client(sent, [item])
    assert asyncio.run(client.event("x-1", 9)) == item
    assert sent == [{"after_sequence": "8", "limit": "1"}]
    assert asyncio.run(client.event("x-1", 10)) is None  # sequence differs


def test_recovery_reads_past_the_last_delivered_event(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from src.dtest.worker import executor_events

    asked = []

    class Executor:
        async def events(self, execution_id, after_sequence=None):
            asked.append(after_sequence)
            return []

    recovery = executor_events.MissedEventRecovery(
        cast(Any, None), cast(Any, Executor()), on_wake=None, after_seconds=120
    )
    run = cast(
        Any,
        SimpleNamespace(
            id="run-1", waiting={"execution_id": "x-1", "operation_id": "o"}
        ),
    )
    asyncio.run(recovery._recover(run, seen=12))
    asyncio.run(recovery._recover(run))
    assert asked == [11, None]


# --- entries the executor cannot confirm ---------------------------------


class _Redis:
    def __init__(self, claimed=()):
        self.acked: list[str] = []
        self.claimed = list(claimed)

    async def xack(self, stream, group, message_id):
        self.acked.append(message_id)

    async def xpending_range(self, stream, group, min, max, count):
        return [
            {"message_id": m, "time_since_delivered": 120000}
            for m, _ in self.claimed
        ]

    async def xclaim(self, stream, group, consumer, idle, ids):
        return self.claimed


class _Confirming:
    """Executor.event: an ExecutorError status per execution id."""

    def __init__(self, statuses):
        self.statuses = statuses

    async def event(self, execution_id, sequence):
        from src.dtest.core.executor.client import ExecutorError

        raise ExecutorError(self.statuses[execution_id], {})


def _wake_fields(execution_id):
    return {
        "event_id": f"e-{execution_id}",
        "execution_id": execution_id,
        "event_type": "execution.completed",
        "event_sequence": "0",
        "payload": "{}",
    }


def _event_consumer(redis, statuses):
    from src.dtest.worker.executor_events import ExecutorEventConsumer

    return ExecutorEventConsumer(
        cast(Any, None),
        cast(Any, redis),
        "s",
        "g",
        "c",
        on_wake=None,
        on_progress=None,
        on_completed=None,
        executor=cast(Any, _Confirming(statuses)),
    )


@pytest.mark.parametrize("status", [400, 404, 422])
def test_entries_the_executor_cannot_read_are_dropped(status):
    # a forged or broken entry (an id that is not a UUID, sequence 0) is
    # refused the same way on every retry: ACK it instead of keeping it
    import asyncio

    redis = _Redis()
    consumer = _event_consumer(redis, {"bad": status})
    asyncio.run(consumer._handle("m1", _wake_fields("bad")))
    assert redis.acked == ["m1"]


def test_a_failing_entry_does_not_hold_back_the_others():
    # the oldest pending entry comes first in every reclaim; if it fails
    # (executor down for it), the ones claimed with it are still handled
    import asyncio

    redis = _Redis(
        claimed=[("m1", _wake_fields("down")), ("m2", _wake_fields("bad"))]
    )
    consumer = _event_consumer(redis, {"down": 503, "bad": 422})
    asyncio.run(consumer._reclaim())
    assert redis.acked == ["m2"]  # m1 stays pending, retried later
