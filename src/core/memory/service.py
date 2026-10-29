"""Project shared memory on the LangGraph Store.

Namespace ("project_memory", project_id); one Store item per section
(``SECTIONS``). A section is a short Markdown body kept as lines::

    {section, lines: [{id, text, author, updated_at, source}],
     version, updated_at}

``author`` records who wrote a line (user | agent); it does not lock the
line. Every write checks the section's version (409 on a stale one), its
character limit and that it has no ``#``/``##`` headings (422; the prompt
uses those levels). Writes of one section are serialised with a Postgres
advisory lock held in the transaction that appends to ``memory_history``.
Items are stored without an embedding index: the whole memory is put in
the prompt.
"""

import difflib
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

from langgraph.store.base import BaseStore
from sqlalchemy import select, text

from core.db import Database, utcnow
from core.models import MemoryHistory

Section = Literal["overview", "preferences", "core_interests", "key_events"]
SECTIONS: tuple[str, ...] = get_args(Section)
SECTION_TITLES = {
    "overview": "Overview",
    "preferences": "Preferences",
    "core_interests": "Core Interests",
    "key_events": "Key Events",
}
Author = Literal["user", "agent"]
# headings of the levels the prompt itself uses
HEADING = re.compile(r"^#{1,2}\s")
LEGACY_SECTIONS = {
    "background": "overview",
    "analysis_preferences": "preferences",
    "report_preferences": "preferences",
    "shared_findings": "key_events",
}

Line = dict[str, Any]


class MemoryEditError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Actor:
    type: Author
    id: str
    session_id: str | None = None
    run_id: str | None = None
    # stored on the lines this actor writes (session/run ids, reason)
    source: dict[str, Any] = field(default_factory=dict)


def new_line_id(taken: set[str] | frozenset[str] = frozenset()) -> str:
    while True:
        line_id = uuid.uuid4().hex[:8]
        if line_id not in taken:
            return line_id


def content_of(lines: list[Line]) -> str:
    return "\n".join(line["text"] for line in lines)


def split_content(content: str) -> list[str]:
    """Body -> lines; trailing spaces and surrounding blank lines dropped."""
    lines = [
        line.rstrip() for line in content.replace("\r\n", "\n").split("\n")
    ]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def check_content(
    section: str, content: str, max_chars: int, before: int = 0
) -> None:
    """422 past the limit, unless the body shrinks (``before`` = old
    length; migrated sections may start over the limit)."""
    if section not in SECTIONS:
        raise MemoryEditError(404, f"unknown memory section: {section}")
    if len(content) > max_chars and len(content) > before:
        raise MemoryEditError(
            422,
            f"{SECTION_TITLES[section]} exceeds {max_chars} characters "
            f"({len(content)})",
        )
    for line in content.split("\n"):
        if HEADING.match(line):
            raise MemoryEditError(
                422, "'# ' and '## ' headings are not allowed; use '###'"
            )


def diff_lines(
    old: list[Line], new_texts: list[str], actor: Actor, now: str
) -> list[Line]:
    """New body as lines, keeping the id/author of every unchanged line.

    Added or changed lines get new ids and ``actor`` as author.
    """
    matcher = difflib.SequenceMatcher(
        a=[line["text"] for line in old], b=new_texts, autojunk=False
    )
    taken = {line["id"] for line in old}
    out: list[Line] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            out.extend(old[i1:i2])
            continue
        for text_ in new_texts[j1:j2]:
            line_id = new_line_id(taken)
            taken.add(line_id)
            out.append(make_line(line_id, text_, actor, now))
    return out


def make_line(line_id: str, text_: str, actor: Actor, now: str) -> Line:
    return {
        "id": line_id,
        "text": text_,
        "author": actor.type,
        "updated_at": now,
        "source": dict(actor.source),
    }


def empty_value(section: str) -> dict[str, Any]:
    return {"section": section, "lines": [], "version": 0, "updated_at": None}


class ProjectMemory:
    def __init__(
        self, store: BaseStore, db: Database, max_chars: dict[str, int]
    ):
        self.store, self.db, self.max_chars = store, db, max_chars

    @staticmethod
    def namespace(project_id: str) -> tuple[str, ...]:
        return ("project_memory", project_id)

    def limit(self, section: str) -> int:
        return self.max_chars[section]

    def view(self, value: dict[str, Any]) -> dict[str, Any]:
        section = value["section"]
        return {
            "section": section,
            "title": SECTION_TITLES[section],
            "content": content_of(value["lines"]),
            "lines": value["lines"],
            "version": value["version"],
            "updated_at": value["updated_at"],
            "max_chars": self.limit(section),
        }

    async def value(self, project_id: str, section: str) -> dict[str, Any]:
        if section not in SECTIONS:
            raise MemoryEditError(404, f"unknown memory section: {section}")
        item = await self.store.aget(self.namespace(project_id), section)
        return item.value if item else empty_value(section)

    async def sections(self, project_id: str) -> list[dict[str, Any]]:
        """All four sections in order, empty ones included."""
        items = {
            i.key: i.value
            for i in await self.store.asearch(
                self.namespace(project_id), limit=100
            )
            if i.key in SECTIONS
        }
        return [self.view(items.get(s) or empty_value(s)) for s in SECTIONS]

    async def section(self, project_id: str, section: str) -> dict[str, Any]:
        return self.view(await self.value(project_id, section))

    async def edit(
        self,
        project_id: str,
        section: str,
        change: Callable[[list[Line]], list[Line]],
        *,
        actor: Actor,
        expected_version: int | None = None,
        action: str = "update",
    ) -> dict[str, Any] | None:
        """Apply ``change`` to the section's lines.

        None when nothing changed. ``change`` may raise MemoryEditError.
        """
        if section not in SECTIONS:
            raise MemoryEditError(404, f"unknown memory section: {section}")
        async with self.db.sessions() as db:
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                {"k": f"project_memory:{project_id}:{section}"},
            )
            before = await self.value(project_id, section)
            if (
                expected_version is not None
                and before["version"] != expected_version
            ):
                raise MemoryEditError(
                    409,
                    "version conflict: current version is "
                    f"{before['version']}",
                )
            lines = change([dict(line) for line in before["lines"]])
            content = content_of(lines)
            if content == content_of(before["lines"]) and [
                line["id"] for line in lines
            ] == [line["id"] for line in before["lines"]]:
                return None
            check_content(
                section,
                content,
                self.limit(section),
                len(content_of(before["lines"])),
            )
            after = {
                "section": section,
                "lines": lines,
                "version": before["version"] + 1,
                "updated_at": utcnow().isoformat(),
            }
            await self.store.aput(
                self.namespace(project_id), section, after, index=False
            )
            db.add(_history_row(project_id, action, before, after, actor))
            await db.commit()
        return self.view(after)

    async def put_content(
        self,
        project_id: str,
        section: str,
        content: str,
        *,
        expected_version: int,
        actor: Actor,
    ) -> dict[str, Any]:
        """Replace the whole body (the user's editor)."""
        now = utcnow().isoformat()
        texts = split_content(content)
        changed = await self.edit(
            project_id,
            section,
            lambda old: diff_lines(old, texts, actor, now),
            actor=actor,
            expected_version=expected_version,
        )
        return changed or await self.section(project_id, section)

    async def save_line(
        self,
        project_id: str,
        section: str,
        text_: str,
        *,
        actor: Actor,
        line_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Add a line, or replace line ``line_id``."""
        text_ = " ".join(text_.split("\n")).strip()
        if not text_:
            raise MemoryEditError(422, "text is empty")
        now = utcnow().isoformat()

        def change(lines: list[Line]) -> list[Line]:
            if line_id is None:
                taken = {line["id"] for line in lines}
                return [
                    *lines,
                    make_line(new_line_id(taken), text_, actor, now),
                ]
            index = _index(lines, line_id)
            lines[index] = make_line(line_id, text_, actor, now)
            return lines

        return await self.edit(project_id, section, change, actor=actor)

    async def delete_line(
        self, project_id: str, section: str, line_id: str, *, actor: Actor
    ) -> dict[str, Any] | None:
        def change(lines: list[Line]) -> list[Line]:
            lines.pop(_index(lines, line_id))
            return lines

        return await self.edit(
            project_id, section, change, actor=actor, action="delete"
        )

    async def history(
        self, project_id: str, section: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        query = select(MemoryHistory).where(
            MemoryHistory.project_id == project_id,
            MemoryHistory.item_id.in_(SECTIONS),
        )
        if section:
            query = query.where(MemoryHistory.item_id == section)
        async with self.db.sessions() as db:
            rows = (
                await db.scalars(
                    query.order_by(MemoryHistory.id.desc()).limit(limit)
                )
            ).all()
        return [_history_view(r) for r in rows]

    async def revert(
        self,
        project_id: str,
        section: str,
        history_id: int,
        *,
        actor: Actor,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Undo one change: the section gets that change's ``before`` body.

        A new version, recorded in history like any other change.
        """
        async with self.db.sessions() as db:
            row = await db.get(MemoryHistory, history_id)
        if (
            row is None
            or row.project_id != project_id
            or (row.item_id != section)
        ):
            raise MemoryEditError(404, "memory history entry not found")
        target = (row.before or {}).get("lines") or []
        changed = await self.edit(
            project_id,
            section,
            lambda _: [dict(line) for line in target],
            actor=actor,
            expected_version=expected_version,
            action="revert",
        )
        return changed or await self.section(project_id, section)

    # --- migration of the former item-per-entry memory ---------------------

    async def migrate_legacy(self, project_id: str) -> int:
        """Old entries (category/title/content) -> lines of the sections.

        background -> overview, analysis/report preferences -> preferences,
        shared_findings -> key_events; each entry becomes "- title: content"
        with its author. A line keeps the entry's id, so a run that stopped
        half way adds nothing twice. Limits are not enforced here. Returns
        the number of entries moved.
        """
        namespace = self.namespace(project_id)
        legacy = [
            i
            for i in await self.store.asearch(namespace, limit=10000)
            if i.key not in SECTIONS and "category" in i.value
        ]
        if not legacy:
            return 0
        legacy.sort(key=lambda i: i.value.get("created_at") or "")
        by_section: dict[str, list[Any]] = {}
        for item in legacy:
            section = LEGACY_SECTIONS.get(item.value["category"], "overview")
            by_section.setdefault(section, []).append(item)
        actor = Actor("agent", "memory_migration")
        for section, items in by_section.items():
            before = await self.value(project_id, section)
            lines = [dict(line) for line in before["lines"]]
            ids = {line["id"] for line in lines}
            for item in items:
                if item.key in ids:
                    continue
                v = item.value
                body = " ".join(str(v.get("content", "")).split())
                lines.append(
                    {
                        "id": item.key,
                        "text": f"- {v.get('title', '').strip()}: {body}",
                        "author": v.get("author", "agent"),
                        "updated_at": v.get("updated_at")
                        or utcnow().isoformat(),
                        "source": v.get("source") or {},
                    }
                )
            if len(lines) != len(before["lines"]):
                after = {
                    "section": section,
                    "lines": lines,
                    "version": before["version"] + 1,
                    "updated_at": utcnow().isoformat(),
                }
                await self.store.aput(namespace, section, after, index=False)
                await self._record(project_id, "migrate", before, after, actor)
        for item in legacy:
            await self.store.adelete(namespace, item.key)
        return len(legacy)

    async def migrate_all_legacy(self) -> int:
        moved = 0
        for namespace in await self.store.alist_namespaces(
            prefix=("project_memory",), max_depth=2, limit=100000
        ):
            if len(namespace) == 2:
                moved += await self.migrate_legacy(namespace[1])
        return moved

    async def _record(
        self,
        project_id: str,
        action: str,
        before: dict[str, Any],
        after: dict[str, Any],
        actor: Actor,
    ) -> None:
        async with self.db.sessions() as db:
            db.add(_history_row(project_id, action, before, after, actor))
            await db.commit()


def _index(lines: list[Line], line_id: str) -> int:
    for i, line in enumerate(lines):
        if line["id"] == line_id:
            return i
    raise MemoryEditError(404, f"memory line {line_id} not found")


def _history_row(
    project_id: str,
    action: str,
    before: dict[str, Any],
    after: dict[str, Any],
    actor: Actor,
) -> MemoryHistory:
    return MemoryHistory(
        project_id=project_id,
        item_id=after["section"],
        action=action,
        before=_snapshot(before),
        after=_snapshot(after),
        actor_type=actor.type,
        actor_id=actor.id,
        session_id=actor.session_id,
        run_id=actor.run_id,
    )


def _snapshot(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": content_of(value["lines"]),
        "lines": value["lines"],
        "version": value["version"],
    }


def _history_view(row: MemoryHistory) -> dict[str, Any]:
    return {
        "id": row.id,
        "section": row.item_id,
        "action": row.action,
        "before": (row.before or {}).get("content", ""),
        "after": (row.after or {}).get("content", ""),
        "version": (row.after or {}).get("version"),
        "actor": {"type": row.actor_type, "id": row.actor_id},
        "session_id": row.session_id,
        "run_id": row.run_id,
        "created_at": row.created_at,
    }


def updated_event(view: dict[str, Any], by: Author) -> dict[str, Any]:
    """``memory_updated`` data: the section as it is now."""
    return {
        **{k: view[k] for k in ("section", "title", "content", "version")},
        "updated_at": view["updated_at"],
        "by": by,
    }


def render_for_prompt(sections: list[dict[str, Any]]) -> str:
    """The whole memory, one ``##`` block per non-empty section."""
    blocks = [
        f"## {s['title']}\n{s['content']}"
        for s in sections
        if s["content"].strip()
    ]
    if not blocks:
        return ""
    return "\n\n".join(["# Project memory", *blocks])
