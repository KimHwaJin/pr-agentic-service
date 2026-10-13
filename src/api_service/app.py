from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api_service.auth.adapters import load_adapter
from api_service.auth.service import SsoService
from api_service.auth.store import AuthStore
from api_service.routers import (
    artifacts,
    auth,
    batch,
    projects,
    sessions,
    users,
    workflows,
)
from core.config import ROOT, Settings
from core.db import NotFound
from core.services import Services


def mount_api(app: FastAPI, settings: Settings) -> None:
    api = APIRouter(prefix=settings.api_prefix)
    for module in (auth, users, projects, sessions, workflows):
        api.include_router(module.router)
    app.include_router(api)
    app.include_router(artifacts.router)
    app.include_router(batch.router)
    app.add_exception_handler(NotFound, _not_found)
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


async def _not_found(request: Request, exc: Exception) -> JSONResponse:
    # a row checked a moment ago was deleted concurrently
    return JSONResponse({"detail": "Not found."}, status_code=404)


def start_api(app: FastAPI, services: Services) -> None:
    settings = services.settings
    store = AuthStore(services.redis, f"{settings.redis_namespace}:auth")
    app.state.sso = SsoService(
        settings, load_adapter(settings), store, services.db
    )
