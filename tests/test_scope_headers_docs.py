"""OpenAPI: X-Project-Id / X-Session-Id only on the gateways using them."""

from fastapi import FastAPI

from src.dtest.api_service.app import mount_api
from src.dtest.core.config import Settings


def _headers() -> dict[tuple[str, str], set[str]]:
    app = FastAPI()
    mount_api(app, Settings())
    found = {}
    for path, item in app.openapi()["paths"].items():
        for method, operation in item.items():
            found[path, method] = {
                p["name"]
                for p in operation.get("parameters", [])
                if p["in"] == "header"
            }
    return found


def test_scope_headers_only_on_the_gateways():
    headers = _headers()
    assert "X-Project-Id" not in headers["/api/v1/users/me", "get"]
    assert "X-Session-Id" not in headers["/api/v1/users/me", "get"]
    executor = headers["/api/v1/executor/{path}", "post"]
    assert {"X-Project-Id", "X-Session-Id"} <= executor
    batch = headers["/api/v1/batch/{path}", "post"]
    assert "X-Project-Id" in batch
    assert "X-Session-Id" not in batch
    scoped = {
        key
        for key, names in headers.items()
        if names & {"X-Project-Id", "X-Session-Id"}
    }
    assert {path for path, _ in scoped} == {
        "/api/v1/executor/{path}",
        "/api/v1/batch/{path}",
    }
