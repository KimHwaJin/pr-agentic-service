"""Deactivating a user cancels their turns and open executor kernels."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast

from src.dtest.api_service.routers import users


def test_deactivation_cancels_runs_and_kernels(monkeypatch):
    results = [["run-1", "run-2"], ["session-1"]]
    cancelled: list[tuple[str, str]] = []
    idle: list[list[str]] = []

    class Session:
        async def scalars(self, statement):
            rows = results.pop(0)
            return SimpleNamespace(all=lambda: rows)

    class Db:
        def sessions(self):
            class Ctx:
                async def __aenter__(self):
                    return Session()

                async def __aexit__(self, *exc):
                    return None

            return Ctx()

    async def request_cancel(services, run_id, reason):
        cancelled.append((run_id, reason))

    async def cancel_idle(services, session_ids, *, reason):
        idle.append(session_ids)

    monkeypatch.setattr(users, "request_cancel", request_cancel)
    monkeypatch.setattr(users, "cancel_idle_executions", cancel_idle)
    services = cast(Any, SimpleNamespace(db=Db()))
    asyncio.run(users.stop_user_work(services, "u-1"))
    assert [r for r, _ in cancelled] == ["run-1", "run-2"]
    assert {reason for _, reason in cancelled} == {"사용자 비활성화"}
    assert idle == [["session-1"]]
