from typing import Any, cast

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
