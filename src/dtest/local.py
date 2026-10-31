"""Entrypoint without the gaia template (outside the company network),
from the repo root: ``python -m src.dtest.local`` (port 8080, or PORT), or
``uvicorn src.dtest.local:app``, which on Windows needs
``--loop asyncio:SelectorEventLoop`` (src/dtest/winloop.py).

Builds a plain FastAPI app and attaches the service as the template's
``app.py`` does (src/dtest/entry.py). ``/api/admin/appReady`` stands in for
the template's readiness route, ``/healthz`` for its liveness route.
"""

import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from src.dtest.core.logging_setup import configure_logging
from src.dtest.entry import attach, worker_health

configure_logging()  # logger.yml (or HCP's own inside the company network)

app = FastAPI(title="pr-agentic-service", version="0.1.0")
attach(app)


@app.get("/api/admin/appReady", include_in_schema=False)
async def app_ready() -> JSONResponse:
    ready = getattr(app.state, "ready", False)
    return JSONResponse({"ready": ready}, 200 if ready else 503)


@app.get("/healthz", include_in_schema=False)
async def healthz() -> JSONResponse:
    alive, stopped = worker_health(app)
    if not alive:
        return JSONResponse({"status": "down", "stopped": stopped}, 503)
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        log_config=None,
        timeout_graceful_shutdown=30,
    )
