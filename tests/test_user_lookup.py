import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

from src.dtest.api_service.routers import users

ME = "0c8a2f86-5d0e-4e55-9a3c-6f2f0f6a1b11"
OTHER = "8921979f-3b7d-4210-85e8-546ae153ff28"


@pytest.fixture
def asked(monkeypatch):
    asked: list[list[str]] = []

    async def users_by_id(services, ids):
        asked.append(ids)
        return {i: SimpleNamespace(id=i) for i in ids if i in (ME, OTHER)}

    monkeypatch.setattr(users, "users_by_id", users_by_id)
    return asked


def _lookup(role: str, ids: str):
    user = cast(Any, SimpleNamespace(id=ME, role=role))
    return asyncio.run(users.lookup_users(cast(Any, None), user, ids))


def test_admins_resolve_anyone_once_per_id(asked):
    found = _lookup("admin", f"{OTHER}, {ME},{OTHER},,unknown")
    assert asked == [[OTHER, ME, "unknown"]]  # one query, no duplicates
    assert set(found) == {OTHER, ME}  # unknown ids are left out


def test_users_resolve_only_themselves(asked):
    found = _lookup("user", f"{OTHER},{ME}")
    assert asked == [[ME]] and set(found) == {ME}


def test_a_page_at_most(asked):
    with pytest.raises(HTTPException) as too_many:
        _lookup("admin", ",".join(f"id-{n}" for n in range(201)))
    assert too_many.value.status_code == 422
