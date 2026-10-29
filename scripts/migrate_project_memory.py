"""Move the former item-per-entry project memory into the four sections.

The service does this itself at startup (``AUTO_MIGRATE``, in
core.bootstrap.migrate); run this where AUTO_MIGRATE is off:

    uv run python scripts/migrate_project_memory.py

background -> overview, analysis_preferences + report_preferences ->
preferences, shared_findings -> key_events; each entry becomes a line
"- {title}: {content}" with its author. Idempotent: moved entries are
removed, and a line keeps its entry's id so a half-done run adds nothing
twice. Section limits are not applied to moved lines.
"""

import asyncio

from langgraph.store.postgres import AsyncPostgresStore

from core.config import get_settings
from core.db import Database
from core.memory.service import ProjectMemory


async def main() -> None:
    settings = get_settings()
    db = Database(settings.database_url, 2)
    try:
        async with AsyncPostgresStore.from_conn_string(
            settings.psycopg_url
        ) as store:
            memory = ProjectMemory(
                store, db, settings.memory_section_max_chars
            )
            moved = await memory.migrate_all_legacy()
        print(f"moved {moved} memory entries")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
