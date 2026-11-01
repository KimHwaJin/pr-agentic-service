"""Issuing and revoking keys: tenant approval is ours alone (2026-11-01)."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.dtest.api_service import deps
from src.dtest.api_service.routers import api_clients as router
from src.dtest.api_service.services import api_clients
from src.dtest.core.config import Settings
from src.dtest.core.models import ApiClient


class _Db:
    def __init__(self):
        self.rows: list[ApiClient] = []

    def sessions(self):
        db = self

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def scalar(self, statement):
                name = statement.compile().params.get("name_1")
                return next((r.id for r in db.rows if r.name == name), None)

            async def scalars(self, statement):
                tenant = statement.compile().params.get("tenant_1")
                return SimpleNamespace(
                    all=lambda: [
                        r
                        for r in db.rows
                        if r.tenant == tenant and r.status != "revoked"
                    ]
                )

            async def get(self, model, key):
                return next((r for r in db.rows if r.id == key), None)

            def add(self, row):
                row.id = row.id or f"c-{len(db.rows) + 1}"
                row.created_at = row.updated_at = api_clients.utcnow()
                db.rows.append(row)

            async def commit(self):
                pass

            async def refresh(self, row):
                pass

        return Session()


@pytest.fixture
def setup():
    db = _Db()
    app = FastAPI()
    app.include_router(router.router)
    app.state.services = SimpleNamespace(
        settings=Settings(executor_tenant_id="ours"), db=db
    )
    app.dependency_overrides[deps.admin_user] = lambda: SimpleNamespace(
        id="admin-1"
    )
    return TestClient(app), db


def test_a_key_of_another_tenant_is_active_at_once(setup):
    client, db = setup
    got = client.post(
        "/admin/api-clients", json={"name": "a", "tenant": "partner"}
    )
    assert got.status_code == 201
    assert got.json()["client"]["status"] == "active"
    assert got.json()["api_key"].startswith("pas_")
    assert db.rows[0].tenant == "partner"


def test_the_tenant_must_be_named(setup):
    client, _ = setup
    got = client.post("/admin/api-clients", json={"name": "a"})
    assert got.status_code == 422


def test_our_tenant_only_on_purpose(setup):
    client, _ = setup
    refused = client.post(
        "/admin/api-clients", json={"name": "a", "tenant": "ours"}
    )
    assert refused.status_code == 422
    ok = client.post(
        "/admin/api-clients",
        json={"name": "a", "tenant": "ours", "own_tenant": True},
    )
    assert ok.status_code == 201 and ok.json()["client"]["status"] == "active"


@pytest.mark.parametrize("tenant", ["dlq", "work"])
def test_reserved_tenants_are_refused(setup, tenant):
    client, _ = setup
    got = client.post(
        "/admin/api-clients", json={"name": "a", "tenant": tenant}
    )
    assert got.status_code == 422


def test_there_is_no_activation_step(setup):
    client, _ = setup
    issued = client.post(
        "/admin/api-clients", json={"name": "a", "tenant": "partner"}
    ).json()
    got = client.post(f"/admin/api-clients/{issued['client']['id']}/activate")
    assert got.status_code in {404, 405}


def test_revoking_a_tenant_revokes_all_its_keys(setup, monkeypatch):
    client, db = setup
    forgotten = []
    monkeypatch.setattr(api_clients, "forget", forgotten.append)
    for name, tenant in [("a", "partner"), ("b", "partner"), ("c", "other")]:
        client.post(
            "/admin/api-clients", json={"name": name, "tenant": tenant}
        )
    got = client.post("/admin/api-clients/tenants/partner/revoke")
    assert got.json() == {"tenant": "partner", "revoked": 2}
    assert [r.status for r in db.rows] == ["revoked", "revoked", "active"]
    assert all(r.revoked_at for r in db.rows[:2])
    assert len(forgotten) == 2
    again = client.post("/admin/api-clients/tenants/partner/revoke")
    assert again.json()["revoked"] == 0
