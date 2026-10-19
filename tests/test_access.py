import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

from api_service.services import access

OWNER = "0c8a2f86-5d0e-4e55-9a3c-6f2f0f6a1b11"


class _Executor:
    def __init__(self, execution):
        self.execution = execution

    async def artifact(self, artifact_id):
        return {
            "artifact_id": artifact_id,
            "produced_by": {"execution_id": "x"},
        }

    async def get(self, execution_id):
        return self.execution


def _owned(execution, user_id):
    services = cast(Any, SimpleNamespace(executor=_Executor(execution)))
    user = cast(Any, SimpleNamespace(id=user_id))
    return asyncio.run(access.owned_artifact(services, user, "a-1"))


def test_batch_artifacts_belong_to_the_batch_owner():
    execution = {
        "trigger": {"type": "BATCH"},
        "context": {"user_id": OWNER, "task_id": "run-7"},
    }
    assert _owned(execution, OWNER)["artifact_id"] == "a-1"
    older = {"trigger_type": "BATCH", "context": {"user_id": OWNER}}
    assert _owned(older, OWNER)["artifact_id"] == "a-1"
    with pytest.raises(HTTPException) as denied:
        _owned(execution, "someone-else")
    assert denied.value.status_code == 404


def test_session_artifacts_still_go_through_the_session(monkeypatch):
    checked = []

    async def session_for(services, user, session_id):
        checked.append(session_id)

    monkeypatch.setattr(access, "session_for", session_for)
    execution = {
        "trigger_type": "INTERACTIVE",
        "context": {"user_id": OWNER, "session_id": "s-1"},
    }
    _owned(execution, "member")
    assert checked == ["s-1"]
    with pytest.raises(HTTPException):  # no session, not a batch
        _owned({"trigger_type": "INTERACTIVE", "context": {}}, OWNER)


def test_executions_without_a_project_belong_to_their_user(monkeypatch):
    async def owner(services, execution_id):
        return None, OWNER

    monkeypatch.setattr(access, "execution_owner", owner)
    services = cast(Any, None)
    asyncio.run(
        access.check_execution(
            services, cast(Any, SimpleNamespace(id=OWNER)), "x"
        )
    )
    with pytest.raises(HTTPException):
        asyncio.run(
            access.check_execution(
                services, cast(Any, SimpleNamespace(id="00123")), "x"
            )
        )
    params: dict[str, str] = {}
    asyncio.run(
        access.scope_execution_list(
            services, cast(Any, SimpleNamespace(id=OWNER)), params
        )
    )
    assert params == {"user_id": OWNER}
