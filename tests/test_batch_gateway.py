"""The pr-batch gateway relays only the routes callers may use."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_service.routers import batch
from api_service.services.api_clients import Caller
from core.config import Settings

ID = "3f2a9c1e-5b7d-4e8a-9c21-7d4e5f6a8b90"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "runtimes"),
        ("GET", "scripts"),
        ("POST", f"scripts/{ID}/versions"),
        ("GET", f"scripts/{ID}/versions/{ID}/content"),
        ("POST", "batches"),
        ("PATCH", f"batches/{ID}"),
        ("POST", f"batches/{ID}/disable"),
        ("POST", f"batches/{ID}/runs/{ID}/cancel"),
    ],
)
def test_caller_routes_are_relayed(method, path):
    assert batch.relayed(method, path)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "batches:disable-by-owner"),
        ("POST", "x/../batches:disable-by-owner"),
        ("POST", "./batches:disable-by-owner"),
        ("GET", "../admin"),
        ("GET", f"batches/{ID}/../../x"),
        ("DELETE", "batches"),
        ("PUT", f"batches/{ID}"),
        ("GET", "batches/not-a-uuid"),
    ],
)
def test_other_routes_are_not(method, path):
    assert not batch.relayed(method, path)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(batch.router)
    app.state.services = SimpleNamespace(settings=Settings())
    return TestClient(app)


@pytest.mark.parametrize(
    "url",
    [
        "/api/v1/batch/x%2F..%2Fbatches:disable-by-owner",
        "/api/v1/batch/%2E%2E%2Fadmin",
        "/api/v1/batch/batches:disable-by-owner",
    ],
)
def test_encoded_traversal_never_reaches_pr_batch(client, monkeypatch, url):
    def upstream(services):
        raise AssertionError("pr-batch was called")

    monkeypatch.setattr(batch, "_client", upstream)
    response = client.post(url, headers={"X-Api-Key": "x", "X-User-Id": "u"})
    assert response.status_code == 404


def test_relay_streams_and_maps_connection_errors(client, monkeypatch):
    import httpx

    async def identity(*args, **kwargs):
        return Caller("c-1", "agent", "partner"), "u1", None

    def handler(request):
        if request.url.path.endswith("/runtimes"):
            return httpx.Response(
                200, content=b"x" * 100_000, headers={"etag": "v1"}
            )
        raise httpx.ConnectError("refused")

    upstream = httpx.AsyncClient(
        base_url="http://batch", transport=httpx.MockTransport(handler)
    )
    monkeypatch.setattr(batch, "key_identity", identity)
    monkeypatch.setattr(batch, "_client", lambda services: upstream)
    ok = client.get("/api/v1/batch/runtimes", headers={"X-Api-Key": "x"})
    assert ok.status_code == 200 and len(ok.content) == 100_000
    assert ok.headers["etag"] == "v1"
    down = client.get("/api/v1/batch/scripts", headers={"X-Api-Key": "x"})
    assert down.status_code == 502


def test_batch_flags_come_from_pr_batch_as_sent(client, monkeypatch):
    """can_enable / can_disable / enable_blocked_reason are pr-batch's:
    the gateway relays them untouched (no rule of its own)."""
    import httpx

    async def identity(*args, **kwargs):
        return Caller("c-1", "agent", "partner"), "u1", None

    async def who(*args, **kwargs):
        return None

    listing = {
        "items": [
            {
                "id": "a",
                "enabled": False,
                "schedule": None,
                "can_enable": False,
                "can_disable": False,
                "enable_blocked_reason": "SCHEDULE_REQUIRED",
            },
            {
                # pr-batch knows the runtime is gone; a schedule is not
                # enough, and the gateway does not second-guess it
                "id": "b",
                "enabled": False,
                "schedule": {"cron": "0 * * * *"},
                "can_enable": False,
                "can_disable": False,
                "enable_blocked_reason": "UNKNOWN_RUNTIME",
            },
        ],
        "next_cursor": None,
    }

    def handler(request):
        if request.url.path.endswith("/enable"):
            return httpx.Response(
                200,
                json={"id": ID, "enabled": True, "can_disable": True},
                headers={"etag": '"3"'},
            )
        return httpx.Response(200, json=listing)

    upstream = httpx.AsyncClient(
        base_url="http://batch", transport=httpx.MockTransport(handler)
    )
    monkeypatch.setattr(batch, "key_identity", identity)
    monkeypatch.setattr(batch, "gateway_identity", who)
    monkeypatch.setattr(batch, "batch_headers", lambda s, w: {})
    monkeypatch.setattr(batch, "_client", lambda services: upstream)
    got = client.get("/api/v1/batch/batches", headers={"X-Api-Key": "x"})
    assert got.json() == listing
    enabled = client.post(
        f"/api/v1/batch/batches/{ID}/enable", headers={"X-Api-Key": "x"}
    )
    assert enabled.headers["etag"] == '"3"'
    assert enabled.json() == {"id": ID, "enabled": True, "can_disable": True}


def test_key_caller_goes_as_its_tenant_with_our_key(monkeypatch):
    """The gateway is the only tenant check pr-batch has (our key is
    allowed every tenant), so the caller's own headers never get through."""
    import httpx

    sent: list[httpx.Request] = []

    async def identity(request, *args, **kwargs):
        caller = Caller("c-1", "partner-agent", "partner")
        request.state.api_client = caller
        return caller, "u1", None

    def handler(request):
        sent.append(request)
        return httpx.Response(200, json={"items": []})

    app = FastAPI()
    app.include_router(batch.router)
    app.state.services = SimpleNamespace(
        settings=Settings(batch_api_key="bat_ours", executor_tenant_id="ours")
    )
    upstream = httpx.AsyncClient(
        base_url="http://batch", transport=httpx.MockTransport(handler)
    )
    monkeypatch.setattr(batch, "key_identity", identity)
    monkeypatch.setattr(batch, "_client", lambda services: upstream)
    got = TestClient(app).get(
        "/api/v1/batch/batches",
        headers={
            "X-Api-Key": "pas_live_theirs",
            "X-Tenant-Id": "someone-else",
            "X-User-Id": "u1",
            "Authorization": "Bearer theirs",
        },
    )
    assert got.status_code == 200
    headers = sent[0].headers
    assert headers["x-api-key"] == "bat_ours"
    assert headers["x-tenant-id"] == "partner"
    assert headers["x-user-id"] == "u1"
    assert "authorization" not in headers


def _admin_client(users: set[str]):
    from contextlib import asynccontextmanager

    from api_service.deps import admin_user

    class Db:
        async def get(self, model, key):
            return object() if key in users else None

    @asynccontextmanager
    async def sessions():
        yield Db()

    app = FastAPI()
    app.include_router(batch.router)
    app.state.services = SimpleNamespace(
        settings=Settings(batch_api_key="bat-key"),
        db=SimpleNamespace(sessions=sessions),
    )
    app.dependency_overrides[admin_user] = lambda: SimpleNamespace(id="adm")
    return TestClient(app)


def test_admin_reads_a_users_batches_as_that_user(monkeypatch):
    import httpx

    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["user"] = request.headers.get("x-user-id")
        seen["tenant"] = request.headers.get("x-tenant-id")
        seen["method"] = request.method
        return httpx.Response(
            200, json={"items": [{"disabled_reason": "USER_DEACTIVATED"}]}
        )

    upstream = httpx.AsyncClient(
        base_url="http://batch", transport=httpx.MockTransport(handler)
    )
    monkeypatch.setattr(batch, "_client", lambda services: upstream)
    client = _admin_client({"b001"})
    ok = client.get("/api/v1/admin/users/b001/batches")
    assert ok.status_code == 200
    assert ok.json()["items"][0]["disabled_reason"] == "USER_DEACTIVATED"
    assert seen == {
        "path": "/api/v1/batches",
        "user": "b001",
        "tenant": Settings().executor_tenant_id,
        "method": "GET",
    }
    assert client.get("/api/v1/admin/users/nobody/batches").status_code == 404


def _gateway_call(monkeypatch, kind: str, method: str, url: str):
    import httpx

    sent: list[httpx.Request] = []

    async def identity(request, *args, **kwargs):
        caller = Caller("c-1", "partner-agent", "partner", kind)
        request.state.api_client = caller
        return caller, "e100", None

    def handler(request):
        sent.append(request)
        return httpx.Response(200, json={"items": []})

    from api_service import errors

    app = FastAPI()
    app.include_router(batch.router)
    errors.install(app)
    app.state.services = SimpleNamespace(
        settings=Settings(batch_api_key="bat_ours", executor_tenant_id="ours")
    )
    upstream = httpx.AsyncClient(
        base_url="http://batch", transport=httpx.MockTransport(handler)
    )
    monkeypatch.setattr(batch, "key_identity", identity)
    monkeypatch.setattr(batch, "_client", lambda services: upstream)
    response = TestClient(app).request(
        method, url, headers={"X-Api-Key": "pas_live_x", "X-User-Id": "e100"}
    )
    return response, sent


def test_standard_key_reads_its_own_batches(monkeypatch):
    got, sent = _gateway_call(
        monkeypatch, "standard", "GET", "/api/v1/batch/batches?limit=5"
    )
    assert got.status_code == 200
    assert sent[0].headers["x-user-id"] == "e100"
    assert dict(sent[0].url.params) == {"limit": "5"}
    denied, sent = _gateway_call(
        monkeypatch, "standard", "GET", "/api/v1/batch/batches?user_id=e200"
    )
    assert denied.status_code == 403 and not sent
    assert denied.json()["error"]["code"] == "FORBIDDEN"


def test_master_key_reads_the_tenants_batches(monkeypatch):
    got, sent = _gateway_call(
        monkeypatch, "master", "GET", "/api/v1/batch/batches?user_id=E200"
    )
    assert got.status_code == 200
    assert "x-user-id" not in sent[0].headers
    assert sent[0].headers["x-tenant-id"] == "partner"
    assert sent[0].url.params["user_id"] == "e200"
    written, sent = _gateway_call(
        monkeypatch, "master", "POST", f"/api/v1/batch/batches/{ID}/runs"
    )
    assert sent[0].headers["x-user-id"] == "e100"
