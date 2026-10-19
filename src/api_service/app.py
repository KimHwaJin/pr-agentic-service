from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api_service import errors
from api_service.auth.adapters import load_adapter
from api_service.auth.service import SsoService
from api_service.auth.store import AuthStore
from api_service.routers import (
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


def mount_api(app: FastAPI, settings: Settings) -> None:
    api = APIRouter(prefix=settings.api_prefix)
    for module in (
        auth,
        users,
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


def start_api(app: FastAPI, services: Services) -> None:
    settings = services.settings
    store = AuthStore(services.redis, f"{settings.redis_namespace}:auth")
    app.state.sso = SsoService(
        settings, load_adapter(settings), store, services.db
    )
