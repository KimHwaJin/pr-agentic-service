"""Optional Phoenix (Arize) tracing of the agent's LangChain/LangGraph runs.

Self-contained and removable: this file, the ``tracing_phoenix.setup()``
call in ``main.py``, the ``phoenix`` dependency group, and the PHOENIX_*
settings. See docs/phoenix-tracing.md.

Off unless PHOENIX_ENDPOINT is set. The settings are the gaia template's
names, read like every other setting (environment > .env > config files):
PHOENIX_ENDPOINT, PHOENIX_API_KEY, and SERVICE_ID as the Phoenix project.
The template registers Phoenix only inside its own workflow files, so our
API and worker runs are traced by this provider, not the template's.
"""

import logging

from core.config import Settings

log = logging.getLogger(__name__)


def setup(settings: Settings) -> None:
    endpoint = settings.phoenix_endpoint.strip()
    if not endpoint:
        return
    try:
        from openinference.instrumentation.langchain import (
            LangChainInstrumentor,
        )
        from phoenix.otel import register
    except ImportError:
        log.warning("phoenix_tracing_skipped: install the 'phoenix' group")
        return
    # OTLP over HTTP (gRPC :4317 is usually not exposed behind an ingress)
    traces = endpoint.rstrip("/")
    if not traces.endswith("/v1/traces"):
        traces += "/v1/traces"
    provider = register(
        endpoint=traces,
        protocol="http/protobuf",
        project_name=settings.service_id,
        api_key=settings.phoenix_api_key or None,
        batch=True,  # export in the background, never on the request path
        set_global_tracer_provider=False,
        verbose=False,
    )
    instrumentor = LangChainInstrumentor()
    if instrumentor.is_instrumented_by_opentelemetry:
        # one instrumentor per process: whoever comes first keeps it
        log.warning("phoenix_tracing_skipped: LangChain already instrumented")
        return
    instrumentor.instrument(tracer_provider=provider)
    log.info(
        "phoenix_tracing_on endpoint=%s project=%s",
        endpoint,
        settings.service_id,
    )
