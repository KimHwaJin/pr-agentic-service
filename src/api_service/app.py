import logging
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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
from core.request_context import HEADER as REQUEST_ID_HEADER
from core.request_context import RequestId
from core.services import Services

audit = logging.getLogger("api_service.audit")


class BodyLimit:
    """413 for request bodies over ``max_bytes`` (base64 images).

    A declared Content-Length is refused before reading; a chunked body
    is counted as it is read and stopped once it passes the limit, so no
    request is held in memory whole beyond it.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        length = headers.get(b"content-length", b"")
        if length.isdigit() and int(length) > self.max_bytes:
            await _too_large(send)
            return
        seen = 0

        async def counted() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    raise HTTPException(413, "Request body is too large.")
            return message

        await self.app(scope, counted, send)


async def _too_large(send: Send) -> None:
    response = errors.error_response(
        413, "too_large", "Request body is too large."
    )
    await response({"type": "http"}, _no_body, send)


async def _no_body() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


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

    app.add_middleware(BodyLimit, max_bytes=settings.request_max_bytes)

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
            expose_headers=[REQUEST_ID_HEADER],
        )
    # outermost: every log line of the request, even a 413, carries the id
    app.add_middleware(RequestId)
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
