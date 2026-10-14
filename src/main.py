"""Service entrypoint: ``uvicorn main:app --app-dir src``.

RUN_MODE=all (default, one container) | api | worker. The deployment runs
everything in one process; the split lets the worker move to its own
Deployment later without code changes.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

import tracing_phoenix  # optional; removable (docs/phoenix-tracing.md)
from api_service.app import mount_api, start_api
from core.bootstrap import build_services
from core.config import get_settings
from worker.runtime import Worker

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
for noisy in ("httpx", "httpx2", "openai"):
    logging.getLogger(noisy).setLevel(
        logging.WARNING
    )  # one INFO line per LLM/executor call is load
settings = get_settings()
tracing_phoenix.setup()
mode = os.environ.get("RUN_MODE", "all")
api_enabled, worker_enabled = mode in {"all", "api"}, mode in {"all", "worker"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with build_services(settings) as (services, pool):
        app.state.services = services
        if api_enabled:
            start_api(app, services)
        worker = Worker(services, pool) if worker_enabled else None
        if worker:
            worker.start()
        app.state.ready = True
        try:
            yield
        finally:
            app.state.ready = False
            if worker:
                await worker.stop()


app = FastAPI(title="pr-agentic-service", version="0.1.0", lifespan=lifespan)
if api_enabled:
    mount_api(app, settings)


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
async def readyz() -> JSONResponse:
    ready = getattr(app.state, "ready", False)
    return JSONResponse({"ready": ready}, 200 if ready else 503)
