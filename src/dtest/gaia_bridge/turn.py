"""One gaia turn = one turn of our chat API.

The run is created and resumed exactly as ``POST /sessions/{id}/runs``
does (``create_run``) and executed by our worker; this follows the
session's events until the run ends or needs the user, streaming the
answer's text as it comes.
"""

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select

from src.dtest.api_service.errors import ApiError
from src.dtest.api_service.schemas.sessions import (
    Resume,
    RunCommand,
    RunCreate,
    RunInput,
)
from src.dtest.api_service.services.runs import create_run
from src.dtest.core.models import Run, RunEvent, User
from src.dtest.core.services import Services
from src.dtest.gaia_bridge import auto_replies, identity

log = logging.getLogger(__name__)

# no event this long: look at the stored events and the run row, in case
# live events were missed (they are best effort)
POLL_SECONDS = 5.0
TERMINAL = {"succeeded", "failed", "cancelled"}

Write = Callable[[str], None]


@dataclass
class TurnResult:
    answer: str
    urls: list[dict[str, str]] = field(default_factory=list)


class Transcript:
    """Text sent to the caller as it arrives; the answer is all of it.

    gaia shows streamed text and, once any was streamed, does not send the
    final answer again, so the final answer is appended unless the stream
    already ended with it.
    """

    def __init__(self, write: Write):
        self.write = write
        self.parts: list[str] = []
        self.gap = False

    @property
    def text(self) -> str:
        return "".join(self.parts)

    def add(self, text: str) -> None:
        if not text:
            return
        if self.gap and self.parts:
            text = "\n\n" + text
        self.gap = False
        self.parts.append(text)
        self.write(text)

    def paragraph(self) -> None:
        """What follows is another model call (after a tool call ...)."""
        self.gap = True

    def finish(self, answer: str) -> str:
        answer = answer.strip()
        if answer and not self.text.rstrip().endswith(answer):
            self.paragraph()
            self.add(answer)
        return self.text


async def run_turn(
    services: Services,
    *,
    employee_id: str,
    gaia_session_id: str,
    query: str,
    write: Write,
) -> TurnResult:
    user = await identity.user_for(services, employee_id)
    if not user.is_active:
        return TurnResult("비활성화된 사용자입니다.")
    session_id = await identity.session_for(
        services, user, gaia_session_id, query
    )
    channel = services.events.channel(session_id)
    queue = services.events.listen_to(channel)  # before the run starts
    try:
        follow = _Follow(services, user, session_id, Transcript(write))
        follow.last = await _last_event_id(services, session_id)
        started = await follow.start(query)
        if started is not None:
            return started
        return await follow.until_done(queue)
    finally:
        services.events.stop_listening(channel, queue)


class _Follow:
    def __init__(
        self,
        services: Services,
        user: User,
        session_id: str,
        transcript: Transcript,
    ):
        self.services, self.user, self.session_id = services, user, session_id
        self.transcript = transcript
        self.run_id = ""
        self.last = 0
        self.answer = ""
        self.error = ""
        self.urls: list[dict[str, str]] = []
        self.answered: set[str] = set()  # interrupt ids replied to

    async def start(self, query: str) -> TurnResult | None:
        """Starts the turn (or answers the pending question with it)."""
        body = RunCreate(input=RunInput(content=query))
        try:
            started = await create_run(
                self.services, self.user, self.session_id, body
            )
        except ApiError as exc:
            if exc.code == "session_busy":
                # an earlier call left before its run ended: follow that one
                self.run_id = exc.extra["run"].id
                return None
            return self.result(exc.detail)
        self.run_id = started.run.id
        return None

    async def until_done(self, queue: asyncio.Queue) -> TurnResult:
        while True:
            try:
                raw = await asyncio.wait_for(queue.get(), POLL_SECONDS)
            except TimeoutError:
                done = await self.catch_up()
                if done is not None:
                    return done
                continue
            done = await self.handle(json.loads(raw))
            if done is not None:
                return done

    async def catch_up(self) -> TurnResult | None:
        for event in await self.services.events.history(
            self.session_id, self.last, self.run_id
        ):
            done = await self.handle(event)
            if done is not None:
                return done
        async with self.services.db.sessions() as db:
            run = await db.get(Run, self.run_id)
        if run is None:
            return self.result("실행 기록을 찾을 수 없습니다.")
        if run.status == "waiting_input" and run.waiting:
            return await self.on_pause(run.waiting)
        return None

    async def handle(self, event: dict[str, Any]) -> TurnResult | None:
        if event.get("run_id") != self.run_id:
            return None
        if "id" in event:
            if event["id"] <= self.last:
                return None
            self.last = event["id"]
        kind, data = event["type"], event.get("data") or {}
        if kind == "token":
            self.transcript.add(data.get("text", ""))
        elif kind in {"tool_call", "agent_switched"}:
            self.transcript.paragraph()
        elif kind == "artifact":
            self.urls.append(self.link(data))
        elif kind == "message_final":
            self.answer = data.get("content", "")
        elif kind == "run_error":
            self.error = data.get("message", "")
        elif kind == "hitl_request":
            return await self.on_pause(data)
        elif kind == "run_status" and data.get("status") in TERMINAL:
            return self.on_end(data["status"])
        return None

    async def on_pause(self, waiting: dict[str, Any]) -> TurnResult | None:
        interrupt_id = waiting.get("interrupt_id", "")
        if interrupt_id in self.answered:
            return None
        self.answered.add(interrupt_id)
        value = auto_replies.reply(waiting)
        if value is not None:
            body = RunCreate(
                command=RunCommand(
                    resume=Resume(interrupt_id=interrupt_id, value=value)
                )
            )
            try:
                await create_run(
                    self.services, self.user, self.session_id, body
                )
                return None
            except ApiError as exc:  # refused: leave it to the user
                log.warning(
                    "gaia_auto_reply_refused run_id=%s type=%s code=%s",
                    self.run_id,
                    waiting.get("type"),
                    exc.code,
                )
        return self.result(auto_replies.ask(waiting))

    def on_end(self, status: str) -> TurnResult:
        if status == "succeeded":
            return self.result(self.answer)
        if status == "cancelled":
            return self.result(self.answer or "분석이 취소되었습니다.")
        log.warning(
            "gaia_run_failed run_id=%s error=%s", self.run_id, self.error
        )
        return self.result(
            self.answer or "분석 중 오류가 발생했습니다. 다시 시도해 주세요."
        )

    def result(self, answer: str) -> TurnResult:
        return TurnResult(self.transcript.finish(answer), self.urls)

    def link(self, artifact: dict[str, Any]) -> dict[str, str]:
        origin = self.services.settings.public_api_origin.rstrip("/")
        return {
            "name": artifact.get("title") or artifact.get("kind", "artifact"),
            "url": artifact.get("lab_url")
            or f"{origin}/view/artifacts/{artifact['artifact_id']}",
        }


async def _last_event_id(services: Services, session_id: str) -> int:
    async with services.db.sessions() as db:
        last = await db.scalar(
            select(func.max(RunEvent.id)).where(
                RunEvent.session_id == session_id
            )
        )
    return last or 0
