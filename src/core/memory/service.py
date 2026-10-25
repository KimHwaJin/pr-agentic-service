"""Project shared memory on the LangGraph Store.

Namespace ("project_memory", project_id); one Store item per memory entry.
Entries written by a user (author=user) are locked: the agent proposes a
change and the user approves it.
Every change is appended to ``memory_history``.
"""

from dataclasses import dataclass
from typing import Any, Literal, get_args

from langgraph.store.base import BaseStore
from sqlalchemy import select

from core.db import Database, new_id, utcnow
from core.models import MemoryHistory

Category = Literal[
    "background",
    "analysis_preferences",
    "report_preferences",
    "shared_findings",
]
CATEGORIES: tuple[str, ...] = get_args(Category)
CATEGORY_TITLES = {
    "background": "프로젝트 배경",
    "analysis_preferences": "분석 선호",
    "report_preferences": "보고서 선호",
    "shared_findings": "공유할 주요 발견",
}
Author = Literal["user", "agent"]


class MemoryItemError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Actor:
    type: Author
    id: str
    session_id: str | None = None
    run_id: str | None = None


class ProjectMemory:
    def __init__(
        self, store: BaseStore, db: Database, item_max: int, total_max: int
    ):
        self.store, self.db, self.item_max, self.total_max = (
            store,
            db,
            item_max,
            total_max,
        )

    @staticmethod
    def namespace(project_id: str) -> tuple[str, ...]:
        return ("project_memory", project_id)

    async def entries(self, project_id: str) -> list[dict[str, Any]]:
        items = await self.store.asearch(
            self.namespace(project_id), limit=1000
        )
        return sorted(
            (self._view(i.key, i.value) for i in items),
            key=lambda v: (v["category"], v["created_at"]),
        )

    async def get(
        self, project_id: str, item_id: str
    ) -> dict[str, Any] | None:
        item = await self.store.aget(self.namespace(project_id), item_id)
        return self._view(item.key, item.value) if item else None

    async def search(
        self, project_id: str, query: str, limit: int
    ) -> list[dict[str, Any]]:
        """Semantic when the Store has an embedding index.

        Otherwise newest first.
        """
        items = await self.store.asearch(
            self.namespace(project_id), query=query or None, limit=limit
        )
        return [self._view(i.key, i.value) | {"score": i.score} for i in items]

    async def create(
        self,
        project_id: str,
        *,
        category: str,
        title: str,
        content: str,
        actor: Actor,
        source: dict | None = None,
    ) -> dict[str, Any]:
        self._check(category, title, content)
        await self._check_total(project_id, len(content))
        now = utcnow().isoformat()
        value = {
            "category": category,
            "title": title.strip(),
            "content": content.strip(),
            "author": actor.type,
            "version": 1,
            "source": source or {},
            "created_at": now,
            "updated_at": now,
        }
        item_id = new_id()
        await self.store.aput(self.namespace(project_id), item_id, value)
        await self._history(project_id, item_id, "create", None, value, actor)
        return self._view(item_id, value)

    async def update(
        self,
        project_id: str,
        item_id: str,
        *,
        expected_version: int,
        actor: Actor,
        title: str | None = None,
        content: str | None = None,
        category: str | None = None,
        approved_by_user: bool = False,
    ) -> dict[str, Any]:
        item = await self.store.aget(self.namespace(project_id), item_id)
        if item is None:
            raise MemoryItemError(404, "memory item not found")
        before = item.value
        if before["version"] != expected_version:
            raise MemoryItemError(
                409,
                f"version conflict: current version is {before['version']}",
            )
        if (
            before["author"] == "user"
            and actor.type == "agent"
            and not approved_by_user
        ):
            raise MemoryItemError(
                423, "user-authored memory requires user approval"
            )
        after = dict(before)
        after.update(
            {
                k: v.strip()
                for k, v in {"title": title, "content": content}.items()
                if v is not None
            }
        )
        if category is not None:
            after["category"] = category
        self._check(after["category"], after["title"], after["content"])
        await self._check_total(
            project_id, len(after["content"]) - len(before["content"])
        )
        if actor.type == "user":
            after["author"] = "user"
        after["version"] = before["version"] + 1
        after["updated_at"] = utcnow().isoformat()
        await self.store.aput(self.namespace(project_id), item_id, after)
        await self._history(
            project_id, item_id, "update", before, after, actor
        )
        return self._view(item_id, after)

    async def delete(
        self,
        project_id: str,
        item_id: str,
        *,
        expected_version: int,
        actor: Actor,
    ) -> None:
        item = await self.store.aget(self.namespace(project_id), item_id)
        if item is None:
            raise MemoryItemError(404, "memory item not found")
        if item.value["version"] != expected_version:
            raise MemoryItemError(
                409,
                "version conflict: current version is "
                f"{item.value['version']}",
            )
        if item.value["author"] == "user" and actor.type == "agent":
            raise MemoryItemError(
                423, "user-authored memory requires user approval"
            )
        await self.store.adelete(self.namespace(project_id), item_id)
        await self._history(
            project_id, item_id, "delete", item.value, None, actor
        )

    async def history(
        self, project_id: str, item_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        query = select(MemoryHistory).where(
            MemoryHistory.project_id == project_id
        )
        if item_id:
            query = query.where(MemoryHistory.item_id == item_id)
        async with self.db.sessions() as db:
            rows = (
                await db.scalars(
                    query.order_by(MemoryHistory.id.desc()).limit(limit)
                )
            ).all()
        return [
            {
                "item_id": r.item_id,
                "action": r.action,
                "before": r.before,
                "after": r.after,
                "actor": {"type": r.actor_type, "id": r.actor_id},
                "session_id": r.session_id,
                "run_id": r.run_id,
                "created_at": r.created_at,
            }
            for r in rows
        ]

    def _check(self, category: str, title: str, content: str) -> None:
        if category not in CATEGORIES:
            raise MemoryItemError(422, f"category must be one of {CATEGORIES}")
        if not title.strip() or not content.strip():
            raise MemoryItemError(422, "title and content are required")
        if len(content) > self.item_max:
            raise MemoryItemError(
                422, f"content exceeds {self.item_max} characters"
            )

    async def _check_total(self, project_id: str, delta: int) -> None:
        if delta <= 0:
            return
        current = sum(
            len(i["content"]) for i in await self.entries(project_id)
        )
        if current + delta > self.total_max:
            raise MemoryItemError(
                422,
                f"project memory is full ({current}/{self.total_max} "
                "characters)",
            )

    async def _history(
        self,
        project_id: str,
        item_id: str,
        action: str,
        before,
        after,
        actor: Actor,
    ) -> None:
        async with self.db.sessions() as db:
            db.add(
                MemoryHistory(
                    project_id=project_id,
                    item_id=item_id,
                    action=action,
                    before=before,
                    after=after,
                    actor_type=actor.type,
                    actor_id=actor.id,
                    session_id=actor.session_id,
                    run_id=actor.run_id,
                )
            )
            await db.commit()

    @staticmethod
    def _view(item_id: str, value: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item_id,
            **{k: value[k] for k in value if k != "source"},
            "source": value.get("source", {}),
        }


def render_for_prompt(
    index: list[dict[str, Any]], relevant: list[dict[str, Any]], max_chars: int
) -> str:
    """Titles of every entry + bodies of the most relevant ones.

    The titles let the agent know what exists.
    """
    if not index:
        return ""
    lines = ["# Project memory (공유 메모리)", "", "## 항목 목록"]
    lines += [
        f"- [{CATEGORY_TITLES[m['category']]}] {m['title']} "
        f"(id={m['id']}, author={m['author']})"
        for m in index
    ]
    body_lines = ["", "## 현재 요청과 관련된 항목 본문"]
    used = sum(len(line) for line in lines)
    for item in relevant:
        entry = f"- {item['title']} (v{item['version']}): {item['content']}"
        if used + len(entry) > max_chars:
            break
        body_lines.append(entry)
        used += len(entry)
    return "\n".join(lines + (body_lines if len(body_lines) > 2 else []))
