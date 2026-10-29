FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

# Third-party dependencies are cached separately from application changes.
COPY pyproject.toml uv.lock ./
# --group phoenix: optional tracing (docs/phoenix-tracing.md); drop it to remove
RUN uv sync --locked --no-dev --group phoenix --no-install-project

# Settings per environment; APP_ENV (Deployment env, or --build-arg APP_ENV=...)
# picks config.{APP_ENV}.yml on top of config.yml (shared by every environment).
ARG APP_ENV=
ENV APP_ENV=${APP_ENV}
COPY logger.yml config*.yml alembic.ini ./
COPY migrations ./migrations
COPY assets ./assets
COPY catalogs ./catalogs
COPY web ./web
COPY src ./src
# UID 1000 matches the Executor image so both can read and write the shared PV.
RUN uv sync --locked --no-dev --group phoenix \
    && useradd --create-home --uid 1000 agentic \
    && chown -R agentic:agentic /app

USER agentic
EXPOSE 8080

# One uvicorn worker per pod: CPU HPA scales pods, background loops must not multiply in-process.
CMD ["uvicorn", "main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8080", "--timeout-graceful-shutdown", "30"]
