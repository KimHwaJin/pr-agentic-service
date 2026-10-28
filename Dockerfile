# Company network: the internal Python 3.11 image with uv
# (--build-arg BASE_IMAGE=...). The default is the public equivalent for
# builds outside it (docker-compose.yml).
ARG BASE_IMAGE=ghcr.io/astral-sh/uv:python3.11-bookworm-slim
FROM ${BASE_IMAGE}

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
COPY logger.yml config*.yml ./
# pr-batch signing key placed at build time (keys/README.md).
COPY keys ./keys
# src/: the gaia template's files and this service under src/dtest/
# (assets, catalogs, migrations, web included). app.py is the template's.
COPY app.py ./
COPY src ./src
# UID 1000 matches the Executor image so both can read and write the shared PV.
RUN uv sync --locked --no-dev --group phoenix \
    && useradd --create-home --uid 1000 agentic \
    && chown -R agentic:agentic /app

USER agentic
EXPOSE 8080

# The gaia template starts one uvicorn worker on config PORT (8080 here):
# CPU HPA scales pods, background loops must not multiply in-process.
# Outside the company network docker-compose.yml runs src/dtest/local.py.
CMD ["python", "app.py"]
