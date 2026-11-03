"""The gaia template's access key check (gaia/core.py AuthMiddleware, on
from GAIA_DEPLOYMENT=development up) stays on the template's APIs: our
paths have their own login and keys, and /dev/ in a browser cannot send
the key."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from api_service.paths import skip_gaia_auth


class AuthMiddleware(BaseHTTPMiddleware):
    """Stand-in for gaia.core.AuthMiddleware."""

    def __init__(self, app, required_key: str):
        super().__init__(app)
        self.required_key = required_key

    async def dispatch(self, request, call_next):
        key = request.headers.get("accesskey")
        if not key:
            return JSONResponse(
                {"detail": "Access key is required"}, status_code=401
            )
        if key != self.required_key:
            return JSONResponse({"detail": "Invalid"}, status_code=403)
        return await call_next(request)


AuthMiddleware.__module__ = "gaia.core"


def _app(add_after: bool = False) -> FastAPI:
    app = FastAPI()

    @app.get("/api/admin/appReady")
    async def ready():
        return {"ok": True}

    @app.get("/api/v1/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/dev/")
    async def dev():
        return {"page": "dev"}

    @app.get("/view/x")
    async def view():
        return {"page": "view"}

    if not add_after:
        app.add_middleware(AuthMiddleware, required_key="k")
    skip_gaia_auth(app)
    if add_after:  # the template adds it in main(), after attach
        app.add_middleware(AuthMiddleware, required_key="k")
    return app


def test_own_paths_skip_the_gaia_key():
    for add_after in (False, True):
        client = TestClient(_app(add_after))
        for path in ("/dev/", "/api/v1/healthz", "/view/x"):
            assert client.get(path).status_code == 200, path


def test_gaia_paths_keep_the_gaia_key():
    for add_after in (False, True):
        client = TestClient(_app(add_after))
        r = client.get("/api/admin/appReady")
        assert r.status_code == 401
        assert r.json() == {"detail": "Access key is required"}
        assert (
            client.get(
                "/api/admin/appReady", headers={"accesskey": "x"}
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/api/admin/appReady", headers={"accesskey": "k"}
            ).status_code
            == 200
        )


def test_other_middleware_named_alike_is_left_alone():
    class AuthMiddleware2(AuthMiddleware):
        pass

    AuthMiddleware2.__name__ = "AuthMiddleware"
    AuthMiddleware2.__module__ = "someone.else"
    app = FastAPI()

    @app.get("/dev/")
    async def dev():
        return {}

    app.add_middleware(AuthMiddleware2, required_key="k")
    skip_gaia_auth(app)
    assert TestClient(app).get("/dev/").status_code == 401
