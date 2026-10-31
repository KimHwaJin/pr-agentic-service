"""WORKFLOW_PROMOTION decides who may promote a workflow."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

from api_service.routers import workflows


class FakeWorkflows:
    def __init__(self):
        self.calls = []

    async def promote(self, workflow_id, user_id, *, admin=False):
        self.calls.append((workflow_id, user_id, admin))
        return {"id": workflow_id}


def _call(mode, role):
    service = FakeWorkflows()
    services = SimpleNamespace(
        settings=SimpleNamespace(workflow_promotion=mode), workflows=service
    )
    request = SimpleNamespace(state=SimpleNamespace(), headers={})
    user = SimpleNamespace(id="u1", role=role)
    asyncio.run(
        workflows.promote_workflow(
            "w1", cast(Any, request), cast(Any, services), cast(Any, user)
        )
    )
    return service.calls


def test_authors_promote_their_own_by_default():
    assert _call("author", "user") == [("w1", "u1", False)]


def test_admin_mode_refuses_other_users():
    with pytest.raises(HTTPException) as refused:
        _call("admin", "user")
    assert refused.value.status_code == 403
    assert _call("admin", "admin") == [("w1", "u1", True)]


def _services(mode):
    return cast(
        Any, SimpleNamespace(settings=SimpleNamespace(workflow_promotion=mode))
    )


def _request(caller=None):
    return cast(Any, SimpleNamespace(state=SimpleNamespace(api_client=caller)))


def test_can_promote_follows_the_mode():
    mine = SimpleNamespace(lifecycle="candidate", author_id="u1")
    theirs = SimpleNamespace(lifecycle="candidate", author_id="u2")
    template = SimpleNamespace(lifecycle="template", author_id="u1")
    user = SimpleNamespace(id="u1", role="user")
    admin = SimpleNamespace(id="u1", role="admin")
    author = _services("author")
    assert workflows._can_promote(author, _request(), mine, user)
    assert not workflows._can_promote(author, _request(), theirs, admin)
    assert not workflows._can_promote(author, _request(), template, user)
    by_admin = _services("admin")
    assert not workflows._can_promote(by_admin, _request(), mine, user)
    assert workflows._can_promote(by_admin, _request(), theirs, admin)
    # an api key caller is never an administrator here
    assert not workflows._can_promote(
        by_admin, _request(caller=object()), theirs, admin
    )
