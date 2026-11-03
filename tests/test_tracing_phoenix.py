"""Phoenix: on from the settings, with the gaia template's names."""

import pytest

import tracing_phoenix
from core.config import Settings

langchain = pytest.importorskip("openinference.instrumentation.langchain")
otel = pytest.importorskip("phoenix.otel")


@pytest.fixture
def calls(monkeypatch):
    seen = {"register": [], "instrument": []}
    cls = langchain.LangChainInstrumentor
    monkeypatch.setattr(
        cls, "instrument", lambda self, **kw: seen["instrument"].append(kw)
    )
    monkeypatch.setattr(cls, "_is_instrumented_by_opentelemetry", False)

    def register(**kw):
        seen["register"].append(kw)
        return "provider"

    monkeypatch.setattr(otel, "register", register)
    return seen


def test_off_without_an_endpoint(calls):
    tracing_phoenix.setup(Settings(phoenix_endpoint=""))
    assert calls == {"register": [], "instrument": []}


def test_registers_with_endpoint_key_and_service_id(calls):
    tracing_phoenix.setup(
        Settings(
            phoenix_endpoint="http://phoenix.corp/",
            phoenix_api_key="k",
            service_id="dtest-local",
        )
    )
    (kw,) = calls["register"]
    assert kw["endpoint"] == "http://phoenix.corp/v1/traces"
    assert kw["api_key"] == "k"
    assert kw["project_name"] == "dtest-local"
    assert kw["set_global_tracer_provider"] is False
    assert calls["instrument"] == [{"tracer_provider": "provider"}]


def test_read_from_config_yml(calls, tmp_path, monkeypatch):
    from core import config

    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    for key in ("APP_ENV", "PHOENIX_ENDPOINT", "SERVICE_ID"):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / "config.yml").write_text(
        "PHOENIX_ENDPOINT: http://phoenix.corp\nSERVICE_ID: from-config\n"
    )
    tracing_phoenix.setup(Settings())
    (kw,) = calls["register"]
    assert kw["project_name"] == "from-config"


def test_skips_when_langchain_is_already_instrumented(calls, monkeypatch):
    cls = langchain.LangChainInstrumentor
    monkeypatch.setattr(cls, "_is_instrumented_by_opentelemetry", True)
    tracing_phoenix.setup(Settings(phoenix_endpoint="http://phoenix.corp"))
    assert calls["instrument"] == []
