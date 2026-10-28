"""Phoenix: our own provider outside, the template's inside."""

import pytest

from src.dtest import tracing_phoenix

langchain = pytest.importorskip("openinference.instrumentation.langchain")


@pytest.fixture
def instrumentor(monkeypatch):
    calls = []
    for key in ("PHOENIX_COLLECTOR_ENDPOINT", "PHOENIX_ENDPOINT"):
        monkeypatch.delenv(key, raising=False)
    cls = langchain.LangChainInstrumentor
    monkeypatch.setattr(cls, "instrument", lambda self, **kw: calls.append(kw))
    return cls, calls


def test_off_without_endpoints(instrumentor):
    tracing_phoenix.setup()
    assert instrumentor[1] == []


def test_template_endpoint_uses_the_global_provider(instrumentor, monkeypatch):
    monkeypatch.setenv("PHOENIX_ENDPOINT", "http://phoenix.corp")
    tracing_phoenix.setup()
    assert instrumentor[1] == [{}]


def test_skips_when_the_template_instrumented_first(instrumentor, monkeypatch):
    cls, calls = instrumentor
    monkeypatch.setenv("PHOENIX_ENDPOINT", "http://phoenix.corp")
    monkeypatch.setattr(cls, "_is_instrumented_by_opentelemetry", True)
    tracing_phoenix.setup()
    assert calls == []
