"""Code sent to the executor: files on the input PV plus a DB index.

Layout under ``<storage_root>/sources/`` (one folder per executor
operation, files in notebook-cell order)::

    users/<employee>/projects/<project>/sessions/<session>/runs/<run>/
      <NN>-<agent tool>/<NN>-<kind>[-<name>].py

The paths are deterministic, so a tool re-run after a resume or a pod
failover writes nothing new and resends the same code (see
``SharedStorage.write_source``). Files are deleted after the retention
period; the executor's own snapshot and the notebook keep the code.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from src.dtest.core.db import Database, utcnow
from src.dtest.core.executor.storage import SharedStorage, safe_part
from src.dtest.core.models import CodeSource

BATCH = 500


@dataclass(frozen=True)
class SourceOwner:
    """Who and which turn a piece of code belongs to."""

    user_id: str
    project_id: str
    session_id: str
    run_id: str

    def folder(self, operation: int, tool: str) -> str:
        return "/".join(
            [
                "users",
                safe_part(self.user_id),
                "projects",
                safe_part(self.project_id),
                "sessions",
                safe_part(self.session_id),
                "runs",
                safe_part(self.run_id),
                f"{operation:02d}-{safe_part(tool)}",
            ]
        )


def file_name(sequence: int, kind: str, name: str | None = None) -> str:
    parts = [f"{sequence:02d}", kind, *([safe_part(name)] if name else [])]
    return "-".join(parts) + ".py"


class CodeSources:
    def __init__(self, db: Database, storage: SharedStorage):
        self.db, self.storage = db, storage

    async def write(
        self,
        code: str,
        *,
        owner: SourceOwner,
        tool_call_id: str,
        relative: str,
        kind: str,
        **meta: Any,
    ) -> dict[str, str]:
        """Write the file (once) and index it; returns the PATH source."""
        source, size = self.storage.write_source(code, relative)
        async with self.db.sessions() as db:
            await db.execute(
                insert(CodeSource)
                .values(
                    user_id=owner.user_id,
                    project_id=owner.project_id,
                    session_id=owner.session_id,
                    run_id=owner.run_id,
                    tool_call_id=tool_call_id,
                    path=source["path"],
                    sha256=source["sha256"],
                    size_bytes=size,
                    kind=kind,
                    created_at=utcnow(),
                    **meta,
                )
                .on_conflict_do_nothing(index_elements=["path"])
            )
            await db.commit()
        return source

    async def link(
        self,
        receipt: dict[str, Any],
        paths: dict[int, str],
    ) -> None:
        """Record which executor step each file became.

        ``paths`` maps the step sequence we sent to its source path.
        """
        operation = receipt["operation"]
        async with self.db.sessions() as db:
            for step in operation["steps"]:
                path = paths.get(step["sequence"])
                if path is None:
                    continue
                await db.execute(
                    update(CodeSource)
                    .where(CodeSource.path == path)
                    .values(
                        execution_id=receipt["execution_id"],
                        operation_id=operation["operation_id"],
                        step_id=step["step_id"],
                    )
                )
            await db.commit()

    async def purge(self, days: int) -> int:
        """Delete files older than ``days``; the index rows stay."""
        cutoff = utcnow() - timedelta(days=days)
        removed = 0
        while True:
            async with self.db.sessions() as db:
                rows = (
                    await db.execute(
                        select(CodeSource.id, CodeSource.path)
                        .where(
                            CodeSource.created_at < cutoff,
                            CodeSource.file_deleted_at.is_(None),
                        )
                        .limit(BATCH)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
                for row in rows:
                    self.storage.delete_source(row.path)
                if rows:
                    await db.execute(
                        update(CodeSource)
                        .where(CodeSource.id.in_([r.id for r in rows]))
                        .values(file_deleted_at=utcnow())
                    )
                await db.commit()
            removed += len(rows)
            if len(rows) < BATCH:
                return removed
