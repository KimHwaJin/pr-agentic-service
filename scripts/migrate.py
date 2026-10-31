"""Run the startup migrations once, outside the service.

For environments that set ``AUTO_MIGRATE: false`` (docs/operations.md):
run this as a deploy step (a Job or a pre-deploy command) with the same
config as the service, then roll out the pods.

    uv run python scripts/migrate.py

Same steps as startup (src.dtest.core.bootstrap.migrate): pgvector extension,
Alembic upgrade, LangGraph checkpoint/store tables, the workflow vector
index and the former project memory move. Exits non-zero on failure, so a
failed migration stops the deploy instead of every pod.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.dtest.core.bootstrap import build_services, migrate  # noqa: E402
from src.dtest.core.config import get_settings  # noqa: E402
from src.dtest.core.logging_setup import configure_logging  # noqa: E402


async def main() -> None:
    settings = get_settings().model_copy(update={"auto_migrate": False})
    async with build_services(settings) as services:
        await migrate(services)
    print("migrations done")


if __name__ == "__main__":
    configure_logging()
    asyncio.run(main())
