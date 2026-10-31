import logging
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api_service import API_PREFIX, errors
from api_service.auth.adapters import load_adapter
from api_service.auth.service import SsoService
from api_service.auth.store import AuthStore
from api_service.routers import (
    api_clients,
    artifacts,
    auth,
    batch,
    batch_reports,
    executor,
    images,
    models,
    projects,
    sessions,
    users,
    workflows,
)
from core.config import ROOT, Settings
from core.services import Services

audit = logging.getLogger("api_service.audit")


def mount_api(app: FastAPI, settings: Settings) -> None:
    api = APIRouter(prefix=API_PREFIX)
    for module in (
        auth,
        users,
        api_clients,
        models,
        projects,
        sessions,
        images,
        workflows,
        executor,
        batch_reports,
    ):
        api.include_router(module.router)
    app.include_router(api)
    app.include_router(artifacts.router)
    app.include_router(batch.router)
    # the view pages' libraries, served here: no CDN in the closed network
    app.mount(
        "/view/assets",
        StaticFiles(directory=Path(__file__).parent / "static/vendor"),
        name="view-assets",
    )
    errors.install(app)
    _caller_headers_together(app)

    @app.middleware("http")
    async def refuse_large_bodies(request: Request, call_next):
        """413 before a too large body is read (base64 images)."""
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > settings.request_max_bytes:
            return JSONResponse(
                {"detail": "Request body is too large.", "code": "too_large"},
                status_code=413,
            )
        return await call_next(request)

    @app.middleware("http")
    async def audit_key_callers(request: Request, call_next):
        """One line per request of a key caller (client, user, result)."""
        response = await call_next(request)
        caller = getattr(request.state, "api_client", None)
        if caller is not None:
            audit.info(
                "api_client_request client=%s tenant=%s user=%s method=%s "
                "path=%s status=%s",
                caller.name,
                caller.tenant,
                getattr(request.state, "caller_user_id", ""),
                request.method,
                request.url.path,
                response.status_code,
            )
        return response

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    if settings.env in {"local", "dev"}:
        app.mount(
            "/dev",
            StaticFiles(directory=ROOT / "web/dev", html=True),
            name="dev",
        )


def _caller_headers_together(app: FastAPI) -> None:
    """OpenAPI: X-Api-Key and X-User-Id as one requirement (sent together).

    FastAPI lists two security schemes as alternatives; Swagger would then
    send only one of them.
    """
    build = app.openapi

    def openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema
        schema = build()
        for path in schema.get("paths", {}).values():
            for operation in path.values():
                if isinstance(operation, dict) and operation.get("security"):
                    merged: dict = {}
                    for requirement in operation["security"]:
                        merged.update(requirement)
                    operation["security"] = [merged]
        app.openapi_schema = schema
        return schema

    app.openapi = openapi  # ty: ignore[invalid-assignment]


async def stop_api() -> None:
    """Closes the API's own HTTP clients (pr-batch gateway)."""
    await batch.close_clients()


def start_api(app: FastAPI, services: Services) -> None:
    settings = services.settings
    store = AuthStore(services.redis, f"{settings.redis_namespace}:auth")
    app.state.sso = SsoService(
        settings, load_adapter(settings), store, services.db
    )
