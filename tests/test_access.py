import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

from src.dtest.api_service.services import access

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
        "context": {"user_id": OWNER},
    }
    assert _owned(execution, OWNER)["artifact_id"] == "a-1"
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
    assert params == {}  # the executor scopes it by X-User-Id


def test_an_admin_reading_sees_anyones_artifact(monkeypatch):
    async def session_for(services, user, session_id):
        raise HTTPException(404, "Project not found.")

    monkeypatch.setattr(access, "session_for", session_for)
    services = cast(
        Any,
        SimpleNamespace(
            executor=_Executor(
                {
                    "trigger_type": "INTERACTIVE",
                    "context": {"user_id": OWNER, "session_id": "s-1"},
                }
            )
        ),
    )
    admin = cast(Any, SimpleNamespace(id="a-1", role="admin"))
    found = asyncio.run(
        access.owned_artifact(services, admin, "a-1", admin_read=True)
    )
    assert found["artifact_id"] == "a-1"
    with pytest.raises(HTTPException):  # without the flag: membership
        asyncio.run(access.owned_artifact(services, admin, "a-1"))
    batch = cast(
        Any,
        SimpleNamespace(
            executor=_Executor(
                {"trigger": {"type": "BATCH"}, "context": {"user_id": OWNER}}
            )
        ),
    )
    found = asyncio.run(
        access.owned_artifact(batch, admin, "a-1", admin_read=True)
    )
    assert found["artifact_id"] == "a-1"


@pytest.mark.parametrize(
    ("role", "caller", "expected"),
    [
        ("admin", None, True),
        ("admin", object(), False),  # a key caller naming an admin
        ("user", None, False),
    ],
)
def test_admin_read_is_an_admins_sso_login(role, caller, expected):
    from src.dtest.api_service.routers.artifacts import admin_read

    request = cast(
        Any, SimpleNamespace(state=SimpleNamespace(api_client=caller))
    )
    user = SimpleNamespace(id="u", role=role)
    assert admin_read(request, user) is expected
