"""Builds process-wide services.

Also runs schema setup once per deploy (advisory lock).
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from alembic import command
from alembic.config import Config
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres import AsyncPostgresStore
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis
from sqlalchemy import text

from core.assets import AssetLoader, SkillCatalog, ToolCatalog
from core.checkpoints import PooledPostgresSaver
from core.config import ROOT, Settings
from core.db import Database
from core.embeddings import build_embedder
from core.events import EventBus
from core.executor.client import ExecutorClient
from core.executor.sources import CodeSources
from core.executor.storage import SharedStorage
from core.images import Images
from core.memory.service import ProjectMemory
from core.services import Services
from core.workflows.service import WorkflowService

# LangGraph's checkpointer and store want dict rows.
PgPool = AsyncConnectionPool[AsyncConnection[DictRow]]

MIGRATION_LOCK = 7_340_001
log = logging.getLogger(__name__)


def _alembic_upgrade(settings: Settings) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")


@asynccontextmanager
async def build_services(
    settings: Settings,
) -> AsyncGenerator[Services]:
    db = Database(settings.database_url, settings.db_pool_size)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    pool: PgPool = AsyncConnectionPool(
        settings.psycopg_url,
        connection_class=AsyncConnection[DictRow],
        min_size=1,
        max_size=settings.checkpoint_pool_size,
        timeout=settings.checkpoint_pool_timeout_seconds,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
        open=False,
    )
    await pool.open()
    embedder = build_embedder(settings)  # workflow search only
    # no vector index: project memory is put in the prompt whole
    store = AsyncPostgresStore(pool)
    workflows = WorkflowService(
        db,
        embedder,
        settings.embedding_space,
        settings.embedding_dims,
        settings.workflow_similarity,
    )
    if settings.executor_io_mode == "api":  # no shared PV: tests only
        from core.executor.testmode import build

        executor, storage = build(settings)
    else:
        executor = ExecutorClient(
            settings.executor_base_url,
            settings.executor_timeout_seconds,
            settings.executor_api_key,
            settings.executor_admin_api_key,
            settings.executor_tenant_id,
        )
        storage = SharedStorage(
            settings.storage_root,
            settings.storage_executor_path,
            settings.executor_result_root,
        )
    services = Services(
        settings=settings,
        db=db,
        redis=redis,
        events=EventBus(db, redis, settings.redis_namespace),
        executor=executor,
        storage=storage,
        code_sources=CodeSources(db, storage),
        images=Images(db, settings.storage_root),
        memory=ProjectMemory(store, db, settings.memory_total_max_chars),
        workflows=workflows,
        embedder=embedder,
        checkpointer=PooledPostgresSaver(pool),
        analysis_skills=AssetLoader(
            settings.catalog_roots("skills"), SkillCatalog.load_many
        ),
        knowledge=AssetLoader(
            settings.catalog_roots("knowledge"), SkillCatalog.load_many
        ),
        tools=AssetLoader(
            settings.catalog_roots("tools"), ToolCatalog.load_many
        ),
    )
    if settings.auto_migrate:
        await migrate(services)
    try:
        yield services
    finally:
        await services.events.close()
        await executor.close()
        await redis.aclose()
        await pool.close()
        await db.close()


async def migrate(services: Services) -> None:
    """App tables (Alembic), LangGraph checkpointer/store tables.

    Also the workflow vector index and the move of the former project
    memory entries into the default topics.
    """
    async with services.db.engine.connect() as conn:
        await conn.execute(
            text("SELECT pg_advisory_lock(:k)"), {"k": MIGRATION_LOCK}
        )
        try:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.commit()
            await asyncio.to_thread(_alembic_upgrade, services.settings)
            if isinstance(services.checkpointer, AsyncPostgresSaver):
                await services.checkpointer.setup()
            if isinstance(services.memory.store, AsyncPostgresStore):
                await services.memory.store.setup()
            # former item-per-entry memory -> default topics (idempotent)
            moved = await services.memory.migrate_all_legacy()
            if moved:
                log.info("project_memory_migrated entries=%d", moved)
            await services.workflows.ensure_index()
        finally:
            await conn.execute(
                text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK}
            )
            await conn.commit()
