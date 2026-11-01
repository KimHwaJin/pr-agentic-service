"""Our middleware and error shape stay on our paths.

Inside the company network the gaia template's own APIs share the app
(docs/internal-network.md); none of our request id, body limit, CORS,
audit or error handling may reach them.
"""

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel

from api_service.app import mount_api
from api_service.errors import ApiError
from api_service.paths import is_own
from core.config import Settings
from core.db import NotFound
from core.request_context import HEADER

ORIGIN = "https://front.example"
GAIA_ORIGIN = "https://gaia.example"


class Body(BaseModel):
    name: str


def _app() -> FastAPI:
    app = FastAPI()

    # stand-ins for the gaia template's routes and handlers
    @app.post("/analyst/api/completion")
    async def completion(request: Request, body: Body):
        await request.body()
        return JSONResponse({"ok": True}, headers={HEADER: "gaia-id"})

    @app.get("/api/admin/appReady")
    async def ready():
        return {"ready": True}

    @app.get("/api/common/missing")
    async def missing():
        raise HTTPException(404, "gone")

    @app.get("/api/common/api-error")
    async def api_error():
        raise ApiError(409, "conflict", "ours")

    @app.get("/api/common/not-found")
    async def not_found():
        raise NotFound("row")

    # one of ours, for contrast
    @app.post("/api/v1/echo")
    async def echo(request: Request):
        await request.body()
        request.state.sso_user_id = "u1"
        return {"ok": True}

    @app.get("/api/v1/missing")
    async def our_missing():
        raise HTTPException(404, "gone")

    mount_api(app, Settings(request_max_bytes=1000, cors_origins=[ORIGIN]))
    return app


def test_own_paths():
    assert is_own("/api/v1/projects") and is_own("/api/v1")
    assert is_own("/view/artifacts/a1")
    assert is_own("/dev") and is_own("/dev/index.html")
    for path in (
        "/api/admin/appReady",
        "/api/common/x",
        "/analyst/api/completion",
        "/analyst/gaia/completion",
        "/workflows",
        "/docs",
        "/developer",
    ):
        assert not is_own(path), path


def test_request_id_only_on_our_paths():
    client = TestClient(_app())
    assert client.get("/api/admin/appReady").headers.get(HEADER) is None
    gaia = client.post("/analyst/api/completion", json={"name": "x"})
    assert gaia.headers[HEADER] == "gaia-id"  # left as gaia set it
    assert client.post("/api/v1/echo").headers[HEADER]


def test_body_limit_only_on_our_paths():
    client = TestClient(_app())
    big = "x" * 5000
    gaia = client.post("/analyst/api/completion", json={"name": big})
    assert gaia.status_code == 200
    assert client.post("/api/v1/echo", content=big).status_code == 413


def test_cors_only_on_our_paths():
    client = TestClient(_app())
    preflight = {
        "Origin": GAIA_ORIGIN,
        "Access-Control-Request-Method": "POST",
    }
    # not answered by our CORS middleware: the app (gaia's) decides
    gaia = client.options("/analyst/api/completion", headers=preflight)
    assert gaia.status_code == 405
    assert "access-control-allow-origin" not in gaia.headers
    ours = client.options(
        "/api/v1/echo", headers={**preflight, "Origin": ORIGIN}
    )
    assert ours.status_code == 200
    assert ours.headers["access-control-allow-origin"] == ORIGIN


def test_errors_keep_their_own_shape_on_other_paths():
    client = TestClient(_app(), raise_server_exceptions=False)
    assert client.get("/api/common/missing").json() == {"detail": "gone"}
    invalid = client.post("/analyst/api/completion", json={}).json()
    assert "detail" in invalid and "error" not in invalid
    assert client.get("/api/common/api-error").status_code == 500
    assert client.get("/api/common/not-found").status_code == 500
    # unknown path outside ours: FastAPI's default
    assert client.get("/nowhere").json() == {"detail": "Not Found"}
    ours = client.get("/api/v1/missing").json()
    assert ours["error"]["code"] == "NOT_FOUND"


def test_audit_only_on_our_paths(caplog):
    client = TestClient(_app())
    with caplog.at_level(logging.INFO, logger="api_service.audit"):
        client.post("/analyst/api/completion", json={"name": "x"})
        client.post("/api/v1/echo")
    paths = [r.getMessage() for r in caplog.records]
    assert len(paths) == 1 and "path=/api/v1/echo" in paths[0]


def test_openapi_merges_security_on_our_paths_only():
    app = _app()
    both = [{"a": []}, {"b": []}]

    @app.get("/api/common/secured", openapi_extra={"security": both})
    async def secured():
        return {}

    @app.get("/api/v1/secured", openapi_extra={"security": both})
    async def our_secured():
        return {}

    paths = app.openapi()["paths"]
    assert paths["/api/common/secured"]["get"]["security"] == both
    assert paths["/api/v1/secured"]["get"]["security"] == [{"a": [], "b": []}]
