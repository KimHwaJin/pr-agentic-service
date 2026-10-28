"""Hooks this service into an app someone else builds.

Inside the company network the gaia template builds the FastAPI app
(``GaiaService()``) and replaces its lifespan in ``main()``, so the
template's ``app.py`` calls ``attach`` in between::

    gaia_service = GaiaService()
    from src.dtest.entry import attach
    attach(gaia_service.app)
    gaia_service.main()

Startup and shutdown run in ``DtestLifespan``, an ASGI middleware that
handles the lifespan messages itself, so they survive the template's own
lifespan. Outside the network ``src/dtest/local.py`` attaches the same way
to a plain FastAPI app.

RUN_MODE=all (default, one container) | api | worker. The deployment runs
everything in one process; the split lets the worker move to its own
Deployment later without code changes.
"""

import logging
import os
from contextlib import AsyncExitStack
from typing import Any

from fastapi import FastAPI
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.dtest import tracing_phoenix  # optional (docs/phoenix-tracing.md)
from src.dtest.api_service.app import mount_api, start_api
from src.dtest.core.bootstrap import build_services
from src.dtest.core.config import get_settings
from src.dtest.winloop import use_selector_loop
from src.dtest.worker.runtime import Worker

log = logging.getLogger(__name__)


def run_mode() -> tuple[bool, bool]:
    """(api enabled, worker enabled) from RUN_MODE."""
    mode = os.environ.get("RUN_MODE", "all")
    return mode in {"all", "api"}, mode in {"all", "worker"}


def attach(app: FastAPI) -> None:
    """Adds this service's routes and startup/shutdown to ``app``.

    Call before the app serves anything (before ``uvicorn.run``: on
    Windows it switches uvicorn to the selector loop psycopg needs).
    ``app.state.ready`` is True between our startup and shutdown.
    """
    use_selector_loop()
    settings = get_settings()
    tracing_phoenix.setup()
    api_enabled, _ = run_mode()
    if api_enabled:
        mount_api(app, settings)
    # added last, so outermost: our startup runs before the app's own
    app.add_middleware(DtestLifespan)


class DtestLifespan:
    """Starts the services and worker on ``lifespan.startup``, stops them
    on ``lifespan.shutdown``, then passes each message on to the app."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "lifespan":
            await self.app(scope, receive, send)
            return
        app: Any = scope["app"]
        stack = AsyncExitStack()
        state = {"started": False, "failed": False}

        async def on_receive() -> Message:
            message = await receive()
            if message["type"] == "lifespan.startup":
                try:
                    await self._start(app, stack)
                except BaseException:
                    state["failed"] = True
                    await stack.aclose()
                    raise
                state["started"] = True
            elif message["type"] == "lifespan.shutdown":
                await self._stop(app, stack)
            return message

        try:
            await self.app(scope, on_receive, send)
        except BaseException as exc:
            if state["started"]:  # the app's own startup failed after ours
                await self._stop(app, stack)
            if not state["failed"]:
                raise
            # Ours failed before the app saw startup. Say so to the server:
            # an unanswered startup reads as "lifespan unsupported" and
            # uvicorn would serve without the services.
            log.exception("dtest_startup_failed")
            await send(
                {"type": "lifespan.startup.failed", "message": repr(exc)}
            )

    async def _start(self, app: Any, stack: AsyncExitStack) -> None:
        settings = get_settings()
        api_enabled, worker_enabled = run_mode()
        services = await stack.enter_async_context(build_services(settings))
        app.state.services = services
        if api_enabled:
            start_api(app, services)
        if worker_enabled:
            worker = Worker(services)
            worker.start()
            stack.push_async_callback(worker.stop)
        app.state.ready = True

    async def _stop(self, app: Any, stack: AsyncExitStack) -> None:
        app.state.ready = False
        await stack.aclose()
