"""Optional Phoenix (Arize) tracing of the agent's LangChain/LangGraph runs.

Self-contained and removable: this file, the ``tracing_phoenix.setup()``
call in ``main.py``, the ``phoenix`` dependency group, and the PHOENIX_*
lines in docker-compose.yml / Dockerfile. See docs/phoenix-tracing.md.

Off unless PHOENIX_COLLECTOR_ENDPOINT is set. Configuration is the standard
Phoenix environment: PHOENIX_COLLECTOR_ENDPOINT, PHOENIX_API_KEY,
PHOENIX_PROJECT_NAME.
"""

import logging
import os

log = logging.getLogger(__name__)


def setup() -> None:
    endpoint = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT")
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
        project_name=os.environ.get(
            "PHOENIX_PROJECT_NAME", "pr-agentic-service"
        ),
        batch=True,  # export in the background, never on the request path
        set_global_tracer_provider=False,
        verbose=False,
    )
    LangChainInstrumentor().instrument(tracer_provider=provider)
    log.info("phoenix_tracing_on endpoint=%s", endpoint)
