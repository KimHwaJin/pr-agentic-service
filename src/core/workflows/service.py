"""Workflow assets: candidate (author only) -> template (everyone, searchable).

Search embeds the user's question and compares it with each template's
example questions (``user_queries``) through a pgvector HNSW index; without
an embedding model it falls back to keyword matching so local development
still works.
"""

from typing import Any

from langchain_core.embeddings import Embeddings
from sqlalchemy import Text, cast, func, or_, select, text, update

from core.assets import SkillCatalog, ToolCatalog
from core.db import Database, utcnow
from core.models import Workflow, WorkflowQueryVector
from core.workflows import spec


class WorkflowError(Exception):
    def __init__(
        self, status: int, message: str, details: list[str] | None = None
    ):
        super().__init__(message)
        self.status, self.details = status, details or []


class WorkflowService:
    def __init__(
        self,
        db: Database,
        embedder: Embeddings | None,
        model: str,
        dims: int,
        threshold: float,
    ):
        self.db, self.embedder, self.model, self.dims, self.threshold = (
            db,
            embedder,
            model,
            dims,
            threshold,
        )

    async def ensure_index(self) -> None:
        if not self.embedder:
            return
        name = f"ix_wqv_hnsw_{self.dims}"
        ddl = (
            f"CREATE INDEX IF NOT EXISTS {name} ON workflow_query_vectors "
            "USING hnsw "
            f"((embedding::vector({self.dims})) vector_cosine_ops) "
            "WHERE active"
        )
        async with self.db.engine.begin() as conn:
            await conn.execute(text(ddl))

    def validate(
        self,
        document: dict[str, Any],
        skills: SkillCatalog,
        tools: ToolCatalog,
    ) -> dict[str, Any]:
        errors = spec.validate(document, skills, tools)
        if errors:
            raise WorkflowError(422, "invalid workflow", errors)
        return spec.normalize(document)

    async def create(
        self,
        *,
        author_id: str,
        document: dict[str, Any],
        user_queries: list[str],
        tags: list[str],
        source_run_id: str | None = None,
        source_workflow_id: str | None = None,
    ) -> Workflow:
        queries = _clean_queries(user_queries)
        async with self.db.sessions() as db:
            workflow = Workflow(
                name=document["workflow"]["name"],
                user_request=document["workflow"]["user_request"],
                document=document,
                user_queries=queries,
                tags=sorted({t.strip().lower() for t in tags if t.strip()}),
                author_id=author_id,
                source_run_id=source_run_id,
                source_workflow_id=source_workflow_id,
            )
            db.add(workflow)
            await db.commit()
        await self._index(workflow)
        return await self.get(workflow.id)

    async def get(self, workflow_id: str) -> Workflow:
        async with self.db.sessions() as db:
            workflow = await db.get(Workflow, workflow_id)
        if workflow is None or workflow.deleted_at is not None:
            raise WorkflowError(404, "workflow not found")
        return workflow

    async def readable(self, workflow_id: str, user_id: str) -> Workflow:
        workflow = await self.get(workflow_id)
        if workflow.lifecycle != "template" and workflow.author_id != user_id:
            raise WorkflowError(404, "workflow not found")
        return workflow

    async def owned(self, workflow_id: str, user_id: str) -> Workflow:
        workflow = await self.get(workflow_id)
        if workflow.author_id != user_id:
            raise WorkflowError(
                403, "only the author can change this workflow"
            )
        return workflow

    async def browse(
        self,
        user_id: str,
        *,
        lifecycle: str | None,
        q: str | None,
        tag: str | None,
    ) -> list[Workflow]:
        query = select(Workflow).where(
            Workflow.deleted_at.is_(None),
            or_(
                Workflow.lifecycle == "template", Workflow.author_id == user_id
            ),
        )
        if lifecycle:
            query = query.where(Workflow.lifecycle == lifecycle)
        if q:
            query = query.where(
                or_(
                    Workflow.name.ilike(f"%{q}%"),
                    Workflow.user_request.ilike(f"%{q}%"),
                )
            )
        if tag:
            query = query.where(Workflow.tags.contains([tag.lower()]))
        async with self.db.sessions() as db:
            return list(
                (
                    await db.scalars(
                        query.order_by(Workflow.updated_at.desc()).limit(200)
                    )
                ).all()
            )

    async def update(
        self,
        workflow_id: str,
        user_id: str,
        *,
        expected_revision: int,
        **changes: Any,
    ) -> Workflow:
        async with self.db.sessions() as db:
            workflow = await db.get(
                Workflow, workflow_id, with_for_update=True
            )
            if workflow is None or workflow.deleted_at is not None:
                raise WorkflowError(404, "workflow not found")
            if workflow.author_id != user_id:
                raise WorkflowError(
                    403, "only the author can change this workflow"
                )
            if workflow.revision != expected_revision:
                raise WorkflowError(
                    409,
                    "revision conflict: current revision is "
                    f"{workflow.revision}",
                )
            if (document := changes.get("document")) is not None:
                workflow.document = document
                workflow.name = document["workflow"]["name"]
                workflow.user_request = document["workflow"]["user_request"]
            if (queries := changes.get("user_queries")) is not None:
                workflow.user_queries = _clean_queries(queries)
            if (tags := changes.get("tags")) is not None:
                workflow.tags = sorted(
                    {t.strip().lower() for t in tags if t.strip()}
                )
            workflow.revision += 1
            await db.commit()
        await self._index(workflow)
        return await self.get(workflow_id)

    async def promote(self, workflow_id: str, user_id: str) -> Workflow:
        await self.owned(workflow_id, user_id)
        async with self.db.sessions() as db:
            await db.execute(
                update(Workflow)
                .where(Workflow.id == workflow_id)
                .values(lifecycle="template")
            )
            await db.commit()
        workflow = await self.get(workflow_id)
        await self._index(workflow)
        return workflow

    async def clone(
        self, workflow_id: str, user_id: str, name: str | None
    ) -> Workflow:
        source = await self.readable(workflow_id, user_id)
        document = dict(source.document)
        document["workflow"] = dict(
            document["workflow"], name=name or source.name
        )
        return await self.create(
            author_id=user_id,
            document=document,
            user_queries=source.user_queries,
            tags=source.tags,
            source_workflow_id=source.id,
        )

    async def delete(
        self, workflow_id: str, user_id: str, is_admin: bool = False
    ) -> None:
        if is_admin:
            await self.get(workflow_id)
        else:
            await self.owned(workflow_id, user_id)
        async with self.db.sessions() as db:
            await db.execute(
                update(Workflow)
                .where(Workflow.id == workflow_id)
                .values(deleted_at=utcnow())
            )
            await db.execute(
                update(WorkflowQueryVector)
                .where(WorkflowQueryVector.workflow_id == workflow_id)
                .values(active=False)
            )
            await db.commit()

    async def reindex(self, workflow_id: str, user_id: str) -> Workflow:
        workflow = await self.owned(workflow_id, user_id)
        await self._index(workflow)
        return await self.get(workflow_id)

    async def search(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Templates only.

        Returns [{workflow, similarity, matched_query}] best first.
        """
        if self.embedder is None:
            return await self._keyword_search(query, limit)
        vector = await self.embedder.aembed_query(query)
        expr = f"(embedding::vector({self.dims}))"
        sql = text(
            f"""
            SELECT DISTINCT ON (v.workflow_id) v.workflow_id, v.query,
                   1 - ({expr} <=> CAST(:q AS vector({self.dims})))
                     AS similarity
            FROM workflow_query_vectors v
            JOIN workflows w ON w.id = v.workflow_id
            WHERE v.active AND v.model = :model AND v.revision = w.revision
              AND w.lifecycle = 'template' AND w.deleted_at IS NULL
            ORDER BY v.workflow_id, {expr} <=> CAST(:q AS vector({self.dims}))
            """
        )
        async with self.db.sessions() as db:
            rows = (
                await db.execute(sql, {"q": str(vector), "model": self.model})
            ).all()
            hits = sorted(
                (r for r in rows if r.similarity >= self.threshold),
                key=lambda r: -r.similarity,
            )[:limit]
            workflows = {
                w.id: w
                for w in (
                    await db.scalars(
                        select(Workflow).where(
                            Workflow.id.in_([h.workflow_id for h in hits])
                        )
                    )
                ).all()
            }
        return [
            {
                "workflow": workflows[h.workflow_id],
                "similarity": round(float(h.similarity), 4),
                "matched_query": h.query,
            }
            for h in hits
        ]

    async def _keyword_search(
        self, query: str, limit: int
    ) -> list[dict[str, Any]]:
        words = [w for w in query.split() if len(w) >= 2][:8]
        if not words:
            return []
        haystack = func.concat(
            Workflow.name,
            " ",
            Workflow.user_request,
            " ",
            cast(Workflow.user_queries, Text),
        )
        async with self.db.sessions() as db:
            rows = (
                await db.scalars(
                    select(Workflow).where(
                        Workflow.lifecycle == "template",
                        Workflow.deleted_at.is_(None),
                        or_(*[haystack.ilike(f"%{w}%") for w in words]),
                    )
                )
            ).all()
        ranked = sorted(
            rows,
            key=lambda w: (
                -sum(
                    word.lower()
                    in f"{w.name} {w.user_request} {w.user_queries}".lower()
                    for word in words
                )
            ),
        )
        return [
            {"workflow": w, "similarity": None, "matched_query": None}
            for w in ranked[:limit]
        ]

    async def _index(self, workflow: Workflow) -> None:
        """Re-embed the current revision.

        Vectors are active only for a live template.
        """
        async with self.db.sessions() as db:
            await db.execute(
                update(WorkflowQueryVector)
                .where(WorkflowQueryVector.workflow_id == workflow.id)
                .values(active=False)
            )
            state = "not_indexed"
            if self.embedder and workflow.user_queries:
                try:
                    vectors = await self.embedder.aembed_documents(
                        workflow.user_queries
                    )
                    db.add_all(
                        WorkflowQueryVector(
                            workflow_id=workflow.id,
                            revision=workflow.revision,
                            query=q,
                            model=self.model,
                            embedding=v,
                            active=workflow.lifecycle == "template"
                            and workflow.deleted_at is None,
                        )
                        for q, v in zip(
                            workflow.user_queries, vectors, strict=True
                        )
                    )
                    state = "ready"
                except Exception:  # noqa: BLE001 - keep the asset; reindex later
                    state = "failed"
            await db.execute(
                update(Workflow)
                .where(Workflow.id == workflow.id)
                .values(index_state=state)
            )
            await db.commit()


def _clean_queries(queries: list[str]) -> list[str]:
    seen: list[str] = []
    for q in queries:
        q = q.strip()
        if q and q not in seen:
            seen.append(q[:4000])
    return seen[:1000]
