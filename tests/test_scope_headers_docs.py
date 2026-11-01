"""OpenAPI: X-Project-Id / X-Session-Id only on the gateways using them."""

from fastapi import FastAPI

from src.dtest.api_service.app import mount_api
from src.dtest.core.config import Settings


def _operations() -> dict:
    app = FastAPI()
    mount_api(app, Settings())
    return app.openapi()["paths"]


def _headers() -> dict[tuple[str, str], set[str]]:
    found = {}
    for path, item in _operations().items():
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


def test_sso_only_apis_show_no_caller_headers():
    paths = _operations()
    sso_only = [
        ("/api/v1/admin/api-clients", "get"),
        ("/api/v1/admin/users", "get"),
        ("/api/v1/admin/users/{user_id}", "patch"),
        ("/api/v1/auth/dev/role", "post"),
    ]
    for path, method in sso_only:
        operation = paths[path][method]
        assert not operation.get("security"), path
        assert not [
            p for p in operation.get("parameters", []) if p["in"] == "header"
        ], path
    assert paths["/api/v1/models"]["get"].get("security")


def test_every_operation_has_its_own_id():
    # client generators key on operationId; the gateways serve several
    # methods from one function
    ids = [
        operation["operationId"]
        for item in _operations().values()
        for operation in item.values()
    ]
    assert len(ids) == len(set(ids))
