from typing import Any, cast

from worker.executor_events import matches


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

    from worker import executor_events

    delivered = []

    async def deliver(db, event):
        delivered.append(event)
        return "run-1"

    class Executor:
        async def events(self, execution_id):
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

    from worker import executor_events

    class Executor:
        async def events(self, execution_id):
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

    from worker import executor_events

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
