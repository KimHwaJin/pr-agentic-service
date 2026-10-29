import logging

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.dtest.api_service import API_PREFIX, errors
from src.dtest.api_service.auth.adapters import load_adapter
from src.dtest.api_service.auth.service import SsoService
from src.dtest.api_service.auth.store import AuthStore
from src.dtest.api_service.routers import (
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
from src.dtest.core.config import DTEST_ROOT, Settings
from src.dtest.core.services import Services

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
    errors.install(app)
    _caller_headers_together(app)

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
            StaticFiles(directory=DTEST_ROOT / "web/dev", html=True),
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


def start_api(app: FastAPI, services: Services) -> None:
    settings = services.settings
    store = AuthStore(services.redis, f"{settings.redis_namespace}:auth")
    app.state.sso = SsoService(
        settings, load_adapter(settings), store, services.db
    )
