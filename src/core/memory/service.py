"""Project shared memory on the LangGraph Store.

A project's memory is a list of topics (``DEFAULT_TOPICS`` until the
project edits it), kept as one Store item in ("project_memory_topics",
project_id)::

    {topics: [{id, title, description, max_chars}], version, updated_at}

Each topic's body is one Store item in ("project_memory", project_id)
keyed by the topic id, a short Markdown body kept as lines::

    {topic, lines: [{id, text, author, updated_at, source}],
     version, updated_at}

``author`` records who wrote a line (user | agent); it does not lock the
line. Every write checks the topic's version (409 on a stale one), its
character limit and that it has no ``#``/``##`` headings (422; the prompt
uses those levels). Writes of one topic are serialised with a Postgres
advisory lock held in the transaction that appends to ``memory_history``.
Editing a topic (same id) keeps its body; replacing or removing one moves
the body to ``memory_history`` (``topic_replaced`` / ``topic_removed``),
from where ``restore`` brings the topic back. Items are stored without
an embedding index: the whole memory is put in the prompt.
"""

import difflib
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from langgraph.store.base import BaseStore
from sqlalchemy import or_, select, text

from core.db import Database, utcnow
from core.models import MemoryHistory

Author = Literal["user", "agent"]
Topic = dict[str, Any]
Line = dict[str, Any]

# the memory of a project that never edited its topics; existing bodies
# are keyed by these ids
DEFAULT_TOPICS: tuple[Topic, ...] = (
    {
        "id": "overview",
        "title": "Overview",
        "description": "프로젝트의 배경·목적·대상(무엇을 왜 분석하는지)",
        "max_chars": 500,
    },
    {
        "id": "preferences",
        "title": "Preferences",
        "description": "분석 방식·보고서 형식·용어에 대한 사용자 선호 "
        '("앞으로는 표로", "수율은 % 소수 첫째 자리")',
        "max_chars": 500,
    },
    {
        "id": "core_interests",
        "title": "Core Interests",
        "description": "사용자가 계속 관심을 두는 제품·공정·설비·지표",
        "max_chars": 500,
    },
    {
        "id": "key_events",
        "title": "Key Events",
        "description": "날짜가 있는 사건·결정 (설비 교체, 기준 변경, 목표 "
        "확정 등). 날짜(YYYY-MM-DD)로 시작, 최신이 위",
        "max_chars": 700,
    },
)
DEFAULT_TOTAL_CHARS = sum(t["max_chars"] for t in DEFAULT_TOPICS)
MAX_TOPICS = 6
MIN_TOPIC_CHARS = 100
TITLE_MAX_CHARS = 40
DESCRIPTION_MAX_CHARS = 200
# headings of the levels the prompt itself uses
HEADING = re.compile(r"^#{1,2}\s")
LEGACY_SECTIONS = {
    "background": "overview",
    "analysis_preferences": "preferences",
    "report_preferences": "preferences",
    "shared_findings": "key_events",
}
TOPIC_ACTIONS = ("topic_removed", "topic_replaced")


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


def check_content(topic: Topic, content: str, before: int = 0) -> None:
    """422 past the limit, unless the body shrinks (``before`` = old
    length; a migrated body or a lowered limit may start over it)."""
    max_chars = topic["max_chars"]
    if len(content) > max_chars and len(content) > before:
        raise MemoryEditError(
            422,
            f"{topic['title']} exceeds {max_chars} characters "
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


def empty_value(topic_id: str) -> dict[str, Any]:
    return {"topic": topic_id, "lines": [], "version": 0, "updated_at": None}


def topic_meta(topic: Topic) -> Topic:
    return {k: topic[k] for k in ("id", "title", "description", "max_chars")}


def check_topics(
    topics: list[dict[str, Any]], known: set[str], total_max_chars: int
) -> list[dict[str, Any]]:
    """Normalised copies of the requested topics, or 422.

    A topic with an ``id`` must be one of ``known`` (ids are generated
    here, never chosen by the client).
    """
    if not topics:
        raise MemoryEditError(422, "at least one topic is needed")
    if len(topics) > MAX_TOPICS:
        raise MemoryEditError(422, f"at most {MAX_TOPICS} topics")
    out, ids, titles = [], set(), set()
    for raw in topics:
        topic_id = raw.get("id") or None
        if topic_id is not None:
            if topic_id not in known:
                raise MemoryEditError(422, f"unknown topic id: {topic_id}")
            if topic_id in ids:
                raise MemoryEditError(422, f"topic {topic_id} given twice")
            ids.add(topic_id)
        title = " ".join(str(raw.get("title") or "").split())
        if not title:
            raise MemoryEditError(422, "a topic needs a title")
        if len(title) > TITLE_MAX_CHARS:
            raise MemoryEditError(
                422, f"title over {TITLE_MAX_CHARS} characters: {title}"
            )
        if title.casefold() in titles:
            raise MemoryEditError(422, f"two topics are titled {title}")
        titles.add(title.casefold())
        description = " ".join(str(raw.get("description") or "").split())
        if len(description) > DESCRIPTION_MAX_CHARS:
            raise MemoryEditError(
                422,
                f"{title}: description over {DESCRIPTION_MAX_CHARS} "
                "characters",
            )
        max_chars = raw.get("max_chars")
        if (
            not isinstance(max_chars, int)
            or isinstance(max_chars, bool)
            or max_chars < MIN_TOPIC_CHARS
        ):
            raise MemoryEditError(
                422, f"{title}: max_chars must be at least {MIN_TOPIC_CHARS}"
            )
        out.append(
            {
                "id": topic_id,
                "title": title,
                "description": description,
                "max_chars": max_chars,
                "replace": bool(raw.get("replace")) and topic_id is not None,
            }
        )
    total = sum(t["max_chars"] for t in out)
    if total > total_max_chars:
        raise MemoryEditError(
            422,
            f"limits add up to {total} characters, over the total "
            f"{total_max_chars}",
        )
    return out


def new_topic_id(taken: set[str]) -> str:
    while True:
        topic_id = "t" + uuid.uuid4().hex[:7]
        if topic_id not in taken:
            return topic_id


class ProjectMemory:
    def __init__(
        self,
        store: BaseStore,
        db: Database,
        total_max_chars: int = DEFAULT_TOTAL_CHARS,
    ):
        self.store, self.db = store, db
        self.total_max_chars = total_max_chars

    @staticmethod
    def namespace(project_id: str) -> tuple[str, ...]:
        return ("project_memory", project_id)

    @staticmethod
    def topics_namespace(project_id: str) -> tuple[str, ...]:
        return ("project_memory_topics", project_id)

    # --- topics ------------------------------------------------------------

    async def topic_list(self, project_id: str) -> dict[str, Any]:
        """{topics, version, updated_at, total_max_chars}; version 0 =
        the defaults, never edited."""
        item = await self.store.aget(
            self.topics_namespace(project_id), "topics"
        )
        value = item.value if item else None
        return {
            "topics": [
                topic_meta(t)
                for t in (value["topics"] if value else DEFAULT_TOPICS)
            ],
            "version": value["version"] if value else 0,
            "updated_at": value["updated_at"] if value else None,
            "total_max_chars": self.total_max_chars,
        }

    async def topics(self, project_id: str) -> list[Topic]:
        return (await self.topic_list(project_id))["topics"]

    async def topic(self, project_id: str, topic_id: str) -> Topic:
        for topic in await self.topics(project_id):
            if topic["id"] == topic_id:
                return topic
        raise MemoryEditError(404, f"unknown memory topic: {topic_id}")

    async def put_topics(
        self,
        project_id: str,
        topics: list[dict[str, Any]],
        *,
        expected_version: int,
        actor: Actor,
    ) -> dict[str, Any]:
        """Replace the whole topic list.

        A topic with its id keeps its body (title/description/limit may
        change); one without an id is new and empty. ``replace: true`` on
        a known id gives it a new id and an empty body. Bodies of replaced
        and dropped topics go to history, from where ``restore`` brings
        them back.
        """
        async with self.db.sessions() as db:
            await _lock(db, f"project_memory:{project_id}:topics")
            current = await self.topic_list(project_id)
            if current["version"] != expected_version:
                raise MemoryEditError(
                    409,
                    "version conflict: current topics version is "
                    f"{current['version']}",
                )
            old = {t["id"]: t for t in current["topics"]}
            wanted = check_topics(topics, set(old), self.total_max_chars)
            taken = set(old)
            new_list, replaced_by = [], {}
            for t in wanted:
                topic_id = t["id"]
                if topic_id is None or t["replace"]:
                    new_id = new_topic_id(taken)
                    taken.add(new_id)
                    if topic_id is not None:
                        replaced_by[topic_id] = new_id
                    topic_id = new_id
                new_list.append(topic_meta({**t, "id": topic_id}))
            kept = {t["id"] for t in new_list}
            gone = [t for t in current["topics"] if t["id"] not in kept]
            if [topic_meta(t) for t in current["topics"]] == new_list:
                return current
            for topic in gone:
                await _lock(db, f"project_memory:{project_id}:{topic['id']}")
                before = await self.value(project_id, topic["id"])
                action = (
                    "topic_replaced"
                    if topic["id"] in replaced_by
                    else "topic_removed"
                )
                after = {
                    **empty_value(topic["id"]),
                    "version": before["version"] + 1,
                    "updated_at": utcnow().isoformat(),
                }
                await self.store.adelete(
                    self.namespace(project_id), topic["id"]
                )
                db.add(
                    _history_row(
                        project_id,
                        action,
                        before,
                        after,
                        actor,
                        topic,
                        {"replaced_by": replaced_by.get(topic["id"])},
                    )
                )
            saved = await self._write_topics(
                project_id, new_list, current["version"]
            )
            await db.commit()
        return saved

    async def _write_topics(
        self, project_id: str, topics: list[Topic], version: int
    ) -> dict[str, Any]:
        value = {
            "topics": topics,
            "version": version + 1,
            "updated_at": utcnow().isoformat(),
        }
        await self.store.aput(
            self.topics_namespace(project_id), "topics", value, index=False
        )
        return {**value, "total_max_chars": self.total_max_chars}

    async def restore(
        self, project_id: str, history_id: int, *, actor: Actor
    ) -> dict[str, Any]:
        """Bring back a replaced or removed topic with its body.

        It is added at the end of the list (title, description and limit
        as they were), so the topic limits must leave room for it (422).
        """
        async with self.db.sessions() as db:
            row = await db.get(MemoryHistory, history_id)
            if (
                row is None
                or row.project_id != project_id
                or row.action not in TOPIC_ACTIONS
            ):
                raise MemoryEditError(404, "removed topic not found")
            topic = (row.before or {}).get("topic")
            if not topic:
                raise MemoryEditError(404, "removed topic not found")
            await _lock(db, f"project_memory:{project_id}:topics")
            current = await self.topic_list(project_id)
            if any(t["id"] == topic["id"] for t in current["topics"]):
                raise MemoryEditError(409, f"{topic['title']} is there")
            title = topic["title"]
            if any(
                t["title"].casefold() == title.casefold()
                for t in current["topics"]
            ):
                title = f"{title} (복원)"[:TITLE_MAX_CHARS]
            new_list = [
                *current["topics"],
                topic_meta({**topic, "title": title}),
            ]
            check_topics(
                new_list,
                {t["id"] for t in new_list},
                self.total_max_chars,
            )
            await _lock(db, f"project_memory:{project_id}:{topic['id']}")
            before = await self.value(project_id, topic["id"])
            after = {
                "topic": topic["id"],
                "lines": [dict(line) for line in row.before.get("lines", [])],
                "version": max(
                    before["version"], (row.after or {}).get("version", 0)
                )
                + 1,
                "updated_at": utcnow().isoformat(),
            }
            await self.store.aput(
                self.namespace(project_id), topic["id"], after, index=False
            )
            db.add(
                _history_row(
                    project_id,
                    "topic_restored",
                    before,
                    after,
                    actor,
                    new_list[-1],
                    {"history_id": history_id},
                )
            )
            await self._write_topics(project_id, new_list, current["version"])
            await db.commit()
        return await self.memory(project_id)

    # --- bodies -------------------------------------------------------------

    def view(self, topic: Topic, value: dict[str, Any]) -> dict[str, Any]:
        return {
            "topic": topic["id"],
            "title": topic["title"],
            "description": topic["description"],
            "max_chars": topic["max_chars"],
            "content": content_of(value["lines"]),
            "lines": value["lines"],
            "version": value["version"],
            "updated_at": value["updated_at"],
        }

    async def value(self, project_id: str, topic_id: str) -> dict[str, Any]:
        item = await self.store.aget(self.namespace(project_id), topic_id)
        return item.value if item else empty_value(topic_id)

    async def contents(self, project_id: str) -> list[dict[str, Any]]:
        """Every topic in order with its body, empty ones included."""
        items = {
            i.key: i.value
            for i in await self.store.asearch(
                self.namespace(project_id), limit=100
            )
        }
        return [
            self.view(t, items.get(t["id"]) or empty_value(t["id"]))
            for t in await self.topics(project_id)
        ]

    async def memory(self, project_id: str) -> dict[str, Any]:
        """GET /memory: the topics with their bodies."""
        listing = await self.topic_list(project_id)
        return {
            "topics": await self.contents(project_id),
            "topics_version": listing["version"],
            "total_max_chars": listing["total_max_chars"],
        }

    async def content(self, project_id: str, topic_id: str) -> dict[str, Any]:
        topic = await self.topic(project_id, topic_id)
        return self.view(topic, await self.value(project_id, topic_id))

    async def edit(
        self,
        project_id: str,
        topic_id: str,
        change: Callable[[list[Line]], list[Line]],
        *,
        actor: Actor,
        expected_version: int | None = None,
        action: str = "update",
    ) -> dict[str, Any] | None:
        """Apply ``change`` to the topic's lines.

        None when nothing changed. ``change`` may raise MemoryEditError.
        """
        async with self.db.sessions() as db:
            await _lock(db, f"project_memory:{project_id}:{topic_id}")
            # read under the lock: a topic replaced meanwhile is gone
            topic = await self.topic(project_id, topic_id)
            before = await self.value(project_id, topic_id)
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
            check_content(topic, content, len(content_of(before["lines"])))
            after = {
                "topic": topic_id,
                "lines": lines,
                "version": before["version"] + 1,
                "updated_at": utcnow().isoformat(),
            }
            await self.store.aput(
                self.namespace(project_id), topic_id, after, index=False
            )
            db.add(
                _history_row(project_id, action, before, after, actor, topic)
            )
            await db.commit()
        return self.view(topic, after)

    async def put_content(
        self,
        project_id: str,
        topic_id: str,
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
            topic_id,
            lambda old: diff_lines(old, texts, actor, now),
            actor=actor,
            expected_version=expected_version,
        )
        return changed or await self.content(project_id, topic_id)

    async def save_line(
        self,
        project_id: str,
        topic_id: str,
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

        return await self.edit(project_id, topic_id, change, actor=actor)

    async def delete_line(
        self, project_id: str, topic_id: str, line_id: str, *, actor: Actor
    ) -> dict[str, Any] | None:
        def change(lines: list[Line]) -> list[Line]:
            lines.pop(_index(lines, line_id))
            return lines

        return await self.edit(
            project_id, topic_id, change, actor=actor, action="delete"
        )

    async def history(
        self,
        project_id: str,
        topic_id: str | None = None,
        limit: int = 100,
        *,
        removed: bool = False,
    ) -> list[dict[str, Any]]:
        """Newest first; ``removed`` = only replaced/removed topics."""
        query = select(MemoryHistory).where(
            MemoryHistory.project_id == project_id,
            # rows of the former item-per-entry memory have no lines
            or_(
                MemoryHistory.after.has_key("lines"),
                MemoryHistory.before.has_key("lines"),
            ),
        )
        if topic_id:
            query = query.where(MemoryHistory.item_id == topic_id)
        if removed:
            query = query.where(MemoryHistory.action.in_(TOPIC_ACTIONS))
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
        topic_id: str,
        history_id: int,
        *,
        actor: Actor,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Undo one change: the topic gets that change's ``before`` body.

        A new version, recorded in history like any other change. A
        removed topic comes back with ``restore`` instead.
        """
        async with self.db.sessions() as db:
            row = await db.get(MemoryHistory, history_id)
        if (
            row is None
            or row.project_id != project_id
            or row.item_id != topic_id
        ):
            raise MemoryEditError(404, "memory history entry not found")
        target = (row.before or {}).get("lines") or []
        changed = await self.edit(
            project_id,
            topic_id,
            lambda _: [dict(line) for line in target],
            actor=actor,
            expected_version=expected_version,
            action="revert",
        )
        return changed or await self.content(project_id, topic_id)

    # --- migration of the former item-per-entry memory ---------------------

    async def migrate_legacy(self, project_id: str) -> int:
        """Old entries (category/title/content) -> lines of the default
        topics.

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
            if "category" in i.value and "lines" not in i.value
        ]
        if not legacy:
            return 0
        legacy.sort(key=lambda i: i.value.get("created_at") or "")
        by_topic: dict[str, list[Any]] = {}
        for item in legacy:
            topic_id = LEGACY_SECTIONS.get(item.value["category"], "overview")
            by_topic.setdefault(topic_id, []).append(item)
        defaults = {t["id"]: t for t in DEFAULT_TOPICS}
        actor = Actor("agent", "memory_migration")
        for topic_id, items in by_topic.items():
            before = await self.value(project_id, topic_id)
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
                    "topic": topic_id,
                    "lines": lines,
                    "version": before["version"] + 1,
                    "updated_at": utcnow().isoformat(),
                }
                await self.store.aput(namespace, topic_id, after, index=False)
                await self._record(
                    project_id,
                    "migrate",
                    before,
                    after,
                    actor,
                    defaults[topic_id],
                )
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
        topic: Topic,
    ) -> None:
        async with self.db.sessions() as db:
            db.add(
                _history_row(project_id, action, before, after, actor, topic)
            )
            await db.commit()


async def _lock(db: Any, key: str) -> None:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": key},
    )


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
    topic: Topic,
    extra: dict[str, Any] | None = None,
) -> MemoryHistory:
    meta = topic_meta(topic)
    return MemoryHistory(
        project_id=project_id,
        item_id=topic["id"],
        action=action,
        before={**_snapshot(before), "topic": meta},
        after={**_snapshot(after), "topic": meta, **(extra or {})},
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
    before, after = row.before or {}, row.after or {}
    return {
        "id": row.id,
        "topic": row.item_id,
        "title": (before.get("topic") or {}).get("title"),
        "action": row.action,
        "before": before.get("content", ""),
        "after": after.get("content", ""),
        "version": after.get("version"),
        "replaced_by": after.get("replaced_by"),
        "actor": {"type": row.actor_type, "id": row.actor_id},
        "session_id": row.session_id,
        "run_id": row.run_id,
        "created_at": row.created_at,
    }


def updated_event(view: dict[str, Any], by: Author) -> dict[str, Any]:
    """``memory_updated`` data: the topic as it is now."""
    return {
        **{k: view[k] for k in ("topic", "title", "content", "version")},
        "updated_at": view["updated_at"],
        "by": by,
    }


def render_for_prompt(topics: list[dict[str, Any]]) -> str:
    """The whole memory, one ``##`` block per non-empty topic."""
    blocks = [
        f"## {t['title']}\n{t['content']}"
        for t in topics
        if t["content"].strip()
    ]
    if not blocks:
        return ""
    return "\n\n".join(["# Project memory", *blocks])


def render_topic_index(topics: list[Topic]) -> str:
    """One line per topic, for the agent's tools and the worker prompt."""
    return "\n".join(
        f"- {t['id']}: {t['title']}"
        + (f" — {t['description']}" if t["description"] else "")
        + f" (한도 {t['max_chars']}자)"
        for t in topics
    )
