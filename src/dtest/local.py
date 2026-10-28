"""Entrypoint without the gaia template (outside the company network):
``uvicorn src.dtest.local:app`` from the repo root.

Builds a plain FastAPI app and attaches the service as the template's
``app.py`` does (src/dtest/entry.py). ``/api/admin/appReady`` stands in for
the template's readiness route.
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from src.dtest.core.logging_setup import configure_logging
from src.dtest.entry import attach

configure_logging()  # logger.yml (or HCP's own inside the company network)

app = FastAPI(title="pr-agentic-service", version="0.1.0")
attach(app)


@app.get("/api/admin/appReady", include_in_schema=False)
async def app_ready() -> JSONResponse:
    ready = getattr(app.state, "ready", False)
    return JSONResponse({"ready": ready}, 200 if ready else 503)
