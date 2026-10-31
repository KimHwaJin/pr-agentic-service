"""The pr-batch gateway relays only the routes callers may use."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.dtest.api_service.routers import batch
from src.dtest.core.config import Settings

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
