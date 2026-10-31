"""DOCS_ENABLED: /docs, /redoc and /openapi.json are off unless turned on."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.dtest.api_service.app import docs_urls, hide_docs
from src.dtest.core.config import Settings

DOC_PATHS = ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect")


def _codes(app: FastAPI) -> list[int]:
    client = TestClient(app)
    return [client.get(p).status_code for p in DOC_PATHS]


def test_off_by_default():
    assert Settings().docs_enabled is False
    app = FastAPI(**docs_urls(Settings()))
    assert _codes(app) == [404, 404, 404, 404]


def test_on_when_enabled():
    app = FastAPI(**docs_urls(Settings(docs_enabled=True)))
    assert _codes(app) == [200, 200, 200, 200]


def test_hide_docs_on_an_app_built_elsewhere():
    app = FastAPI()  # docs on, as a template builds it

    @app.get("/kept")
    async def kept():
        return {}

    hide_docs(app)
    assert _codes(app) == [404, 404, 404, 404]
    assert TestClient(app).get("/kept").status_code == 200


def test_attach_hides_the_template_docs(monkeypatch):
    from src.dtest import entry

    monkeypatch.setattr(entry, "use_selector_loop", lambda: None)
    monkeypatch.setattr(entry, "run_mode", lambda: (False, False))
    monkeypatch.setattr(entry, "get_settings", lambda: Settings())
    app = FastAPI()
    entry.attach(app)
    assert _codes(app) == [404, 404, 404, 404]
