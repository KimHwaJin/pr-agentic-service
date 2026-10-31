"""The pr-batch gateway relays only the routes callers may use."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_service.routers import batch
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
        return None, None, None

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
