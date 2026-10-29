"""Background project memory worker.

A finished chat turn marks its project dirty (``mark_dirty``, in the
scheduler's transaction, whether or not the worker runs). Once a project's
chats have been quiet for ``memory_worker_quiet_seconds``, or after
``memory_worker_max_turns`` turns, one worker claims it (FOR UPDATE SKIP
LOCKED + lease), reads the user/assistant messages after its cursor (one
chunk of ``memory_worker_max_input_tokens``) and asks the model, in one
call, for line edits of the project's memory topics (their ids, titles and
descriptions are put in the prompt; formats such as "starts with a date"
live in the descriptions, which the user may edit).

The model may only keep durable facts, preferences, interests and events
the USER stated; code checks every edit (``plan_topic``) and drops the
ones that fail, keeping the rest. A chunk that keeps failing is skipped
after ``MAX_ATTEMPTS`` so a project is never stuck.
"""

import asyncio
import contextlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import json_repair
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import and_, exists, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.dtest.agent.llm import chat_model
from src.dtest.agent.prompts import load_prompt
from src.dtest.core.db import utcnow
from src.dtest.core.memory.service import (
    HEADING,
    Actor,
    Line,
    MemoryEditError,
    Topic,
    content_of,
    make_line,
    new_line_id,
    render_topic_index,
    updated_event,
)
from src.dtest.core.models import (
    ChatSession,
    MemoryExtractionState,
    Message,
    Run,
)
from src.dtest.core.services import Services

log = logging.getLogger(__name__)

State = MemoryExtractionState
ACTOR_ID = "memory_worker"
MAX_ATTEMPTS = 3
RETRY_BASE_SECONDS = 30
LEASE_SECONDS = 600
POLL_SECONDS = 15
FETCH_LIMIT = 500
# per message in the model input (user text is checked in full)
USER_CHARS, ASSISTANT_CHARS = 3000, 1000

ONE_OFF = re.compile(
    r"이번\s*(?:만|에만|세션|대화|분석|보고서|리포트|결과)|이\s*(?:보고서|리포트|분석|세션)\s*만"
    r"|오늘만|지금만|당분간|임시로"
    r"|this\s+(?:time|session|report|analysis)|just\s+for\s+now|for\s+now",
    re.I,
)
URL = re.compile(r"https?://|www\.", re.I)
PATH = re.compile(
    r"[A-Za-z]:\\|\\\\|(?:^|[\s(])~?/[\w.-]+/|\b[\w.-]+/[\w./-]*\.[A-Za-z]\w{0,4}\b"
)
TRIVIAL = {
    "안녕", "안녕하세요", "하이", "헬로", "고마워", "고마워요", "고맙습니다",
    "감사", "감사해요", "감사합니다", "땡큐", "네", "넵", "넹", "예", "응",
    "웅", "ㅇㅇ", "ㅇㅋ", "오케이", "좋아", "좋아요", "좋습니다", "알겠어",
    "알겠어요", "알겠습니다", "확인", "확인했어요", "확인했습니다", "수고",
    "수고하세요", "수고했어", "수고하셨습니다", "잘했어", "굿", "아니",
    "아니요", "아뇨", "계속", "계속해", "계속해줘", "진행", "진행해",
    "진행해줘", "진행해주세요", "ok", "okay", "thanks", "thankyou", "thx",
    "hi", "hello", "yes", "no", "go",
}  # fmt: skip


# --- trigger (scheduler side) ---------------------------------------------


async def mark_dirty(db: AsyncSession, project_id: str, run_id: str) -> None:
    """A turn of the project finished (call inside its transaction).

    A project seen for the first time starts its cursor at this run's
    first message, so turning the worker on does not mine old chats.
    """
    now = utcnow()
    first = (
        select(func.min(Message.created_at))
        .where(Message.run_id == run_id)
        .scalar_subquery()
    )
    await db.execute(
        insert(State)
        .values(
            project_id=project_id,
            processed_until_at=func.coalesce(first, now),
            processed_until_id="",
            dirty=True,
            last_activity_at=now,
            pending_turns=1,
            attempts=0,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=[State.project_id],
            set_={
                "dirty": True,
                "last_activity_at": now,
                "pending_turns": State.pending_turns + 1,
                "updated_at": now,
            },
        )
    )


def claimable(now: datetime, quiet_seconds: float, max_turns: int):
    """Dirty, not leased (or lease over) and quiet long enough or busy."""
    return and_(
        State.dirty.is_(True),
        or_(State.lease_expires_at.is_(None), State.lease_expires_at < now),
        or_(
            State.last_activity_at <= now - timedelta(seconds=quiet_seconds),
            State.pending_turns >= max_turns,
        ),
    )


# --- pure helpers ---------------------------------------------------------


@dataclass
class ChatMessage:
    id: str
    created_at: datetime
    role: str
    content: str
    session_id: str
    run_id: str | None


def normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


def is_trivial(text: str) -> bool:
    """A greeting or short acknowledgement: nothing worth remembering."""
    t = re.sub(r"[\W_]+", "", text.casefold())
    return len(t) <= 2 or t in TRIVIAL or bool(re.fullmatch(r"[ㅋㅎㅠㅜ]+", t))


def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1


def clip(message: ChatMessage) -> str:
    limit = USER_CHARS if message.role == "user" else ASSISTANT_CHARS
    text = message.content.strip()
    return text if len(text) <= limit else text[:limit] + " …(생략)"


def take_chunk(
    messages: list[ChatMessage], max_tokens: int
) -> list[ChatMessage]:
    """The oldest messages that fit the budget (at least one)."""
    chunk: list[ChatMessage] = []
    used = 0
    for message in messages:
        cost = estimate_tokens(clip(message)) + 10
        if chunk and used + cost > max_tokens:
            break
        chunk.append(message)
        used += cost
    return chunk


def parse_ops(text: str) -> list[dict[str, Any]]:
    """The model's ``{"ops": [...]}`` (or a bare list); [] if unreadable."""
    start = min(
        (i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1
    )
    if start < 0:
        return []
    try:
        value = json_repair.loads(text[start:])
    except Exception:  # noqa: BLE001
        return []
    if isinstance(value, dict):
        value = value.get("ops", [])
    if not isinstance(value, list):
        return []
    return [op for op in value if isinstance(op, dict)]


@dataclass
class Plan:
    """What one topic becomes; ``lines`` is None when nothing changes."""

    lines: list[Line] | None
    accepted: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[tuple[dict[str, Any], str]] = field(default_factory=list)


def check_text(text: str) -> str | None:
    if not text:
        return "empty text"
    if HEADING.match(text):
        return "heading"
    if ONE_OFF.search(text):
        return "one-off phrasing"
    if URL.search(text):
        return "url"
    if PATH.search(text):
        return "file path"
    return None


def check_op(
    op: dict[str, Any],
    lines: list[Line],
    user_texts: list[str],
) -> str | None:
    kind = op.get("op")
    if kind not in ("add", "replace", "delete"):
        return f"unknown op {kind!r}"
    index = {line["id"]: line for line in lines}
    if kind in ("replace", "delete") and op.get("line_id") not in index:
        return "line_id not found"
    if kind == "delete":
        return None
    text = " ".join(str(op.get("text") or "").split())
    problem = check_text(text)
    if problem:
        return problem
    quote = normalize(str(op.get("quote") or ""))
    if not quote:
        return "no quote"
    if not any(quote in normalize(t) for t in user_texts):
        return "quote not in a user message"
    if ONE_OFF.search(quote):
        return "one-off phrasing"
    if kind == "replace" and normalize(text) == normalize(
        index[op["line_id"]]["text"]
    ):
        return "replace changes nothing"
    if kind == "add" and any(
        normalize(text) == normalize(line["text"]) for line in lines
    ):
        return "duplicate line"
    return None


def apply_ops(
    lines: list[Line],
    ops: list[dict[str, Any]],
    user_texts: list[str],
    actor: Actor,
    now: str,
) -> tuple[list[Line], list[tuple[dict, int]], list[tuple[dict, str]]]:
    """Valid ops applied in order -> (lines, [(op, growth)], rejected)."""
    work = [dict(line) for line in lines]
    accepted: list[tuple[dict, int]] = []
    rejected: list[tuple[dict, str]] = []
    for op in ops:
        problem = check_op(op, work, user_texts)
        if problem:
            rejected.append((op, problem))
            continue
        before = len(content_of(work))
        kind = op["op"]
        if kind == "delete":
            work = [line for line in work if line["id"] != op["line_id"]]
        else:
            text = " ".join(str(op["text"]).split())
            if kind == "add":
                taken = {line["id"] for line in work}
                work.append(make_line(new_line_id(taken), text, actor, now))
            else:
                work = [
                    make_line(line["id"], text, actor, now)
                    if line["id"] == op["line_id"]
                    else line
                    for line in work
                ]
        accepted.append((op, len(content_of(work)) - before))
    return work, accepted, rejected


def plan_topic(
    lines: list[Line],
    ops: list[dict[str, Any]],
    user_texts: list[str],
    limit: int,
    actor: Actor,
    now: str,
) -> Plan:
    """Validate and apply; growing ops are dropped (last first) to fit."""
    candidates = list(ops)
    dropped: list[tuple[dict, str]] = []
    original = len(content_of(lines))
    while True:
        work, accepted, rejected = apply_ops(
            lines, candidates, user_texts, actor, now
        )
        size = len(content_of(work))
        if size <= limit or size <= original:
            break
        growing = [op for op, growth in accepted if growth > 0]
        if not growing:
            return Plan(None, [], rejected + dropped)
        last = growing[-1]
        candidates = [op for op in candidates if op is not last]
        dropped.append((last, f"topic over {limit} characters"))
    if not accepted:
        return Plan(None, [], rejected + dropped)
    return Plan(work, [op for op, _ in accepted], rejected + dropped)


def render_memory(contents: list[dict[str, Any]]) -> str:
    """Every topic with its lines and ids (``ProjectMemory.contents``)."""
    blocks = []
    for t in contents:
        body = "\n".join(
            f"- [{line['id']}] ({line['author']}) {line['text']}"
            for line in t["lines"]
        )
        blocks.append(
            f"## {t['topic']} ({t['title']}) "
            f"{len(t['content'])}/{t['max_chars']}자\n"
            f"{body or '(비어 있음)'}"
        )
    return "\n\n".join(blocks)


def worker_prompt(topics: list[Topic], today: str) -> str:
    return load_prompt("memory_worker").render(
        today=today, topics=render_topic_index(topics)
    )


def render_chat(messages: list[ChatMessage]) -> str:
    sessions: dict[str, int] = {}
    out = []
    for m in messages:
        n = sessions.setdefault(m.session_id, len(sessions) + 1)
        role = "USER" if m.role == "user" else "ASSISTANT"
        out.append(
            f"[대화{n} {m.created_at:%Y-%m-%d %H:%M}] {role}: {clip(m)}"
        )
    return "\n\n".join(out)


# --- worker ---------------------------------------------------------------


class MemoryWorker:
    def __init__(self, services: Services, owner: str):
        self.services, self.owner = services, owner
        self.settings = services.settings
        self.memory = services.memory
        self.tasks: set[asyncio.Task] = set()
        self.accepting = True
        self._wake = asyncio.Event()

    async def run_forever(self) -> None:
        while self.accepting:
            self._wake.clear()
            free = self.settings.memory_worker_concurrency - len(self.tasks)
            claimed: list[State] = []
            try:
                claimed = await self.claim(free) if free > 0 else []
            except Exception:  # noqa: BLE001 - keep polling
                log.exception("memory_claim_failed")
            for state in claimed:
                task = asyncio.create_task(self.process(state))
                self.tasks.add(task)
                task.add_done_callback(self._done)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), POLL_SECONDS)

    def _done(self, task: asyncio.Task) -> None:
        self.tasks.discard(task)
        self._wake.set()

    async def stop(self, timeout: float) -> None:
        self.accepting = False
        self._wake.set()
        if self.tasks:
            await asyncio.wait(self.tasks, timeout=timeout)
        for task in self.tasks:
            task.cancel()
        async with self.services.db.sessions() as db:
            await db.execute(
                update(State)
                .where(State.lease_owner == self.owner)
                .values(lease_owner=None, lease_expires_at=None)
            )
            await db.commit()

    async def claim(self, limit: int) -> list[State]:
        now = utcnow()
        s = self.settings
        async with self.services.db.sessions() as db:
            rows = (
                await db.scalars(
                    select(State)
                    .where(
                        claimable(
                            now,
                            s.memory_worker_quiet_seconds,
                            s.memory_worker_max_turns,
                        )
                    )
                    .order_by(State.last_activity_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for row in rows:
                row.lease_owner = self.owner
                row.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
            await db.commit()
        return list(rows)

    async def process(self, state: State) -> None:
        chunk: list[ChatMessage] = []
        try:
            messages = await self.messages(state)
            chunk = take_chunk(
                messages, self.settings.memory_worker_max_input_tokens
            )
            if chunk:
                await self.extract(state.project_id, chunk)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("memory_extract_failed project=%s", state.project_id)
            await self.failed(state, chunk, f"{type(exc).__name__}: {exc}")
            return
        await self.advance(state, chunk[-1] if chunk else None)

    async def messages(self, state: State) -> list[ChatMessage]:
        query = (
            select(
                Message.id,
                Message.created_at,
                Message.role,
                Message.content,
                Message.session_id,
                Message.run_id,
            )
            .join(ChatSession, ChatSession.id == Message.session_id)
            .where(
                ChatSession.project_id == state.project_id,
                ChatSession.deleted_at.is_(None),
                Message.role.in_(("user", "assistant")),
            )
            .order_by(Message.created_at, Message.id)
            .limit(FETCH_LIMIT)
        )
        if state.processed_until_at is not None:
            query = query.where(after_cursor(state))
        async with self.services.db.sessions() as db:
            rows = (await db.execute(query)).all()
        return [ChatMessage(*row) for row in rows]

    async def extract(
        self, project_id: str, chunk: list[ChatMessage]
    ) -> list[str]:
        """One model call for the chunk; returns the changed topic ids."""
        user_texts = [m.content for m in chunk if m.role == "user"]
        if all(is_trivial(t) for t in user_texts):
            return []  # covers a chunk with no user message too
        contents = await self.memory.contents(project_id)
        topics = {t["topic"] for t in contents}
        model = await self.model_for(chunk)
        prompt = worker_prompt(
            await self.memory.topics(project_id), f"{utcnow():%Y-%m-%d}"
        )
        request = (
            f"# 현재 프로젝트 메모리\n{render_memory(contents)}\n\n"
            f"# 새 대화\n{render_chat(chunk)}"
        )
        response = await chat_model(self.settings, model).ainvoke(
            [SystemMessage(prompt), HumanMessage(request)]
        )
        ops = parse_ops(response.text)
        by_topic: dict[str, list[dict[str, Any]]] = {}
        for op in ops:
            # "section": the name before topics were editable
            topic_id = op.get("topic") or op.get("section")
            if topic_id in topics:
                by_topic.setdefault(topic_id, []).append(op)
            else:
                log.info("memory_op_rejected reason=topic op=%s", _dump(op))
        actor = Actor(
            "agent",
            ACTOR_ID,
            source={
                "session_ids": sorted({m.session_id for m in chunk}),
                "run_ids": sorted({m.run_id for m in chunk if m.run_id}),
            },
        )
        changed = []
        for topic_id, topic_ops in by_topic.items():
            view = await self.apply(
                project_id, topic_id, topic_ops, user_texts, actor
            )
            if view:
                changed.append(topic_id)
                await self.announce(chunk, view)
        return changed

    async def apply(
        self,
        project_id: str,
        topic_id: str,
        ops: list[dict[str, Any]],
        user_texts: list[str],
        actor: Actor,
    ) -> dict[str, Any] | None:
        """Plan against the current lines; on a version conflict, once more
        (a topic replaced meanwhile is gone: 404, nothing saved)."""
        for attempt in range(2):
            try:
                current = await self.memory.content(project_id, topic_id)
            except MemoryEditError:
                return None
            plan = plan_topic(
                current["lines"],
                ops,
                user_texts,
                current["max_chars"],
                actor,
                utcnow().isoformat(),
            )
            for op, reason in plan.rejected:
                log.info(
                    "memory_op_rejected project=%s reason=%s op=%s",
                    project_id,
                    reason,
                    _dump(op),
                )
            if plan.lines is None:
                return None
            try:
                return await self.memory.edit(
                    project_id,
                    topic_id,
                    lambda _, lines=plan.lines: lines,
                    actor=actor,
                    expected_version=current["version"],
                )
            except MemoryEditError as exc:
                if exc.status == 409 and attempt == 0:
                    continue
                log.warning(
                    "memory_apply_failed project=%s topic=%s: %s",
                    project_id,
                    topic_id,
                    exc,
                )
                return None
        return None

    async def model_for(self, chunk: list[ChatMessage]) -> str:
        """Projects have no model of their own: the model of the latest
        run in the chunk, else the default model."""
        run_ids = [m.run_id for m in reversed(chunk) if m.run_id]
        name = None
        if run_ids:
            async with self.services.db.sessions() as db:
                name = await db.scalar(
                    select(Run.model).where(Run.id == run_ids[0])
                )
        spec = self.settings.model(name) if name else None
        return (spec or self.settings.default_model).name

    async def announce(
        self, chunk: list[ChatMessage], view: dict[str, Any]
    ) -> None:
        """memory_updated to every session of the chunk (its last run)."""
        last_run: dict[str, str] = {}
        for m in chunk:
            if m.run_id:
                last_run[m.session_id] = m.run_id
        data = updated_event(view, "agent")
        for session_id, run_id in last_run.items():
            try:
                await self.services.events.emit(
                    session_id, run_id, "memory_updated", data
                )
            except Exception:  # noqa: BLE001 - the change itself is saved
                log.warning("memory_event_failed session=%s", session_id)

    async def advance(
        self, state: State, last: ChatMessage | None, error: str | None = None
    ) -> None:
        """Move the cursor past ``last``; dirty only if messages remain."""
        async with self.services.db.sessions() as db:
            row = await db.scalar(
                select(State)
                .where(
                    State.project_id == state.project_id,
                    State.lease_owner == self.owner,
                )
                .with_for_update()
            )
            if row is None:
                return  # lease lost
            if last is not None:
                row.processed_until_at = last.created_at
                row.processed_until_id = last.id
            more = row.processed_until_at is not None and await db.scalar(
                select(
                    exists().where(
                        Message.session_id == ChatSession.id,
                        ChatSession.project_id == state.project_id,
                        ChatSession.deleted_at.is_(None),
                        Message.role.in_(("user", "assistant")),
                        after_cursor(row),
                    )
                )
            )
            row.dirty = bool(more)
            if not more:
                row.pending_turns = 0
            row.attempts = 0
            row.last_error = error
            row.lease_owner = row.lease_expires_at = None
            await db.commit()

    async def failed(
        self, state: State, chunk: list[ChatMessage], error: str
    ) -> None:
        attempts = state.attempts + 1
        if attempts >= MAX_ATTEMPTS and chunk:
            log.error(
                "memory_extract_gave_up project=%s messages=%d: %s",
                state.project_id,
                len(chunk),
                error,
            )
            await self.advance(state, chunk[-1], error=error)
            return
        delay = min(RETRY_BASE_SECONDS * 2 ** (attempts - 1), 3600)
        async with self.services.db.sessions() as db:
            await db.execute(
                update(State)
                .where(
                    State.project_id == state.project_id,
                    State.lease_owner == self.owner,
                )
                .values(
                    attempts=attempts,
                    last_error=error,
                    lease_owner=None,
                    # not claimed again before then
                    lease_expires_at=utcnow() + timedelta(seconds=delay),
                )
            )
            await db.commit()


def after_cursor(state: State):
    return tuple_(Message.created_at, Message.id) > tuple_(
        state.processed_until_at, state.processed_until_id
    )


def _dump(op: dict[str, Any]) -> str:
    return json.dumps(op, ensure_ascii=False)[:300]
