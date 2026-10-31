"""Run the startup migrations once, outside the service.

For environments that set ``AUTO_MIGRATE: false`` (docs/operations.md):
run this as a deploy step (a Job or a pre-deploy command) with the same
config as the service, then roll out the pods.

    uv run python scripts/migrate.py

Same steps as startup (core.bootstrap.migrate): pgvector extension,
Alembic upgrade, LangGraph checkpoint/store tables, the workflow vector
index and the former project memory move. Exits non-zero on failure, so a
failed migration stops the deploy instead of every pod.
"""

import asyncio

from core.bootstrap import build_services, migrate
from core.config import get_settings
from core.logging_setup import configure_logging


async def main() -> None:
    settings = get_settings().model_copy(update={"auto_migrate": False})
    async with build_services(settings) as services:
        await migrate(services)
    print("migrations done")


if __name__ == "__main__":
    configure_logging()
    asyncio.run(main())
