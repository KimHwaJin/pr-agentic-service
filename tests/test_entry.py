"""attach(): our startup/shutdown on an app whose lifespan someone else owns
(the gaia template replaces it in GaiaService.main())."""

import asyncio
import re
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI

from src.dtest import entry

ROOT = Path(__file__).resolve().parents[1]


class FakeWorker:
    def __init__(self, services, log):
        self.log = log

    def start(self):
        self.log.append("worker.start")

    async def stop(self):
        self.log.append("worker.stop")


@pytest.fixture
def log(monkeypatch):
    log: list[str] = []

    @asynccontextmanager
    async def build_services(settings):
        log.append("services.open")
        yield "services"
        log.append("services.close")

    monkeypatch.setattr(entry, "build_services", build_services)
    monkeypatch.setattr(entry, "Worker", lambda s: FakeWorker(s, log))
    monkeypatch.setattr(entry, "mount_api", lambda app, s: None)
    monkeypatch.setattr(
        entry, "start_api", lambda app, s: log.append("api.start")
    )
    monkeypatch.delenv("RUN_MODE", raising=False)
    return log


def gaia_like_app(log: list[str]) -> FastAPI:
    app = FastAPI()
    entry.attach(app)

    # what GaiaService.main() does after attach
    @asynccontextmanager
    async def lifespan(_app):
        log.append(f"gaia.start ready={getattr(_app.state, 'ready', None)}")
        yield
        log.append("gaia.stop")

    app.router.lifespan_context = lifespan
    return app


async def run_lifespan(app) -> list[str]:
    """Drives the ASGI lifespan as uvicorn does; returns what app sent."""
    inbox: asyncio.Queue = asyncio.Queue()
    sent: list[str] = []

    async def receive():
        return await inbox.get()

    async def send(message):
        sent.append(message["type"])

    await inbox.put({"type": "lifespan.startup"})
    task = asyncio.create_task(
        app({"type": "lifespan", "asgi": {"version": "3.0"}}, receive, send)
    )
    while not sent:
        await asyncio.sleep(0)
    if sent[-1] == "lifespan.startup.complete":
        assert app.state.ready is True
        await inbox.put({"type": "lifespan.shutdown"})
    await task
    return sent


async def test_startup_and_shutdown_survive_a_replaced_lifespan(log):
    app = gaia_like_app(log)
    sent = await run_lifespan(app)
    assert sent == ["lifespan.startup.complete", "lifespan.shutdown.complete"]
    assert log == [
        "services.open",
        "api.start",
        "worker.start",
        "gaia.start ready=True",
        "worker.stop",
        "services.close",
        "gaia.stop",
    ]
    assert app.state.services == "services"
    assert app.state.ready is False


async def test_failed_startup_is_reported_not_skipped(log, monkeypatch):
    @asynccontextmanager
    async def broken(settings):
        raise ConnectionError("db down")
        yield

    monkeypatch.setattr(entry, "build_services", broken)
    app = gaia_like_app(log)
    # unanswered, uvicorn would take it as "lifespan unsupported" and serve
    assert await run_lifespan(app) == ["lifespan.startup.failed"]
    assert "gaia.start" not in " ".join(log)


async def test_worker_only_mode_starts_no_api(log, monkeypatch):
    monkeypatch.setenv("RUN_MODE", "worker")
    await run_lifespan(gaia_like_app(log))
    assert "api.start" not in log and "worker.start" in log


def test_imports_use_the_src_dtest_package():
    # app.py puts both the repo root and src/ on sys.path: mixing
    # "core.x" and "src.dtest.core.x" would load the same module twice
    old = re.compile(
        r"^\s*(from|import) (dtest|core|api_service|agent|worker)\b", re.M
    )
    offenders = [
        str(path.relative_to(ROOT))
        for folder in ("src", "tests", "scripts")
        for path in (ROOT / folder).rglob("*.py")
        if old.search(path.read_text("utf-8"))
    ]
    assert offenders == []
