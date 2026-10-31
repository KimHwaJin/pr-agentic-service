"""Runs agent turns from the ``runs`` table on any pod.

A run is claimed with FOR UPDATE SKIP LOCKED and a lease. While it waits for
the user or the executor it holds no pod resources (status waiting_*). If a
pod dies, the lease expires and another pod continues from the LangGraph
checkpoint. Every state change is guarded by the lease owner.
"""

import asyncio
import contextlib
import logging
from datetime import timedelta
from time import monotonic
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import or_, select, update

from src.dtest.agent.context import RunContext
from src.dtest.agent.graph import AgentGraphs
from src.dtest.agent.titles import summarize_title
from src.dtest.core.contracts.hitl import PauseRequest
from src.dtest.core.db import affected, get_row, utcnow
from src.dtest.core.events import runs_wake_channel
from src.dtest.core.executor.cancels import cancel_execution
from src.dtest.core.models import (
    ChatSession,
    CodeSource,
    ExecutorInbox,
    Message,
    Project,
    Run,
    RunEvent,
)
from src.dtest.core.services import Services
from src.dtest.worker.executor_events import matches
from src.dtest.worker.memory import mark_dirty

log = logging.getLogger(__name__)
_PAUSE: TypeAdapter = TypeAdapter(PauseRequest)
TERMINAL = {"succeeded", "failed", "cancelled"}
# payload fields of execution.step_handover_* relayed to the session
HANDOVER_FIELDS = ("reason", "paused_seconds", "finished_during_handover")


class LeaseLost(Exception):
    pass


class TooManyAttempts(RuntimeError):
    """The run was claimed again and again without reaching a pause."""


class RunScheduler:
    def __init__(self, services: Services, graphs: AgentGraphs, owner: str):
        self.services, self.graphs, self.owner = services, graphs, owner
        self.settings = services.settings
        self.tasks: set[asyncio.Task] = set()
        self.background: set[asyncio.Task] = (
            set()
        )  # fire-and-forget work such as session titles
        self.accepting = True
        self._wake = asyncio.Event()

    async def notify(self, run_id: str | None = None) -> None:
        await self.services.events.wake_runs(run_id or "")

    async def run_forever(self) -> None:
        listener = asyncio.create_task(self._listen())
        failures = 0
        try:
            while self.accepting:
                # before claiming, so a wake during the claim is not lost
                self._wake.clear()
                free = self.settings.run_concurrency - len(self.tasks)
                try:
                    runs = await self._claim(free) if free > 0 else []
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - DB blip: keep claiming
                    failures += 1
                    log.exception("run_claim_failed attempt=%d", failures)
                    await asyncio.sleep(min(30.0, 2.0**failures))
                    continue
                failures = 0
                for run in runs:
                    task = asyncio.create_task(self._execute(run))
                    self.tasks.add(task)
                    task.add_done_callback(self._task_done)
                if len(runs) == free and free > 0:
                    continue  # the queue may hold more work
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._wake.wait(), self.settings.run_poll_seconds
                    )
        finally:
            listener.cancel()

    def _task_done(self, task: asyncio.Task) -> None:
        self.tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            # _execute could not even record the failure (DB down): the
            # lease runs out and another claim retries the run
            log.error("run_task_crashed", exc_info=task.exception())
        # a slot is free: claim queued work now, not at the next poll
        self._wake.set()

    async def drain(self, timeout: float) -> None:
        """Graceful shutdown.

        Stop claiming, let running turns finish, then release leases.
        """
        self.accepting = False
        self._wake.set()
        if self.tasks:
            await asyncio.wait(self.tasks, timeout=timeout)
        for task in self.tasks:
            task.cancel()
        async with self.services.db.sessions() as db:
            await db.execute(
                update(Run)
                .where(Run.lease_owner == self.owner, Run.status == "running")
                .values(
                    status="queued",
                    lease_owner=None,
                    lease_expires_at=None,
                    # a shutdown is not a failed attempt
                    attempts=Run.attempts - 1,
                )
            )
            await db.commit()

    async def _listen(self) -> None:
        """Wake-ups over Redis; reconnects (polling covers the gap)."""
        while True:
            pubsub = self.services.redis.pubsub()
            try:
                await pubsub.subscribe(
                    runs_wake_channel(self.settings.redis_namespace)
                )
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        self._wake.set()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - reconnect
                log.exception("run_wake_listener_reconnect")
                await asyncio.sleep(1)
            finally:
                await pubsub.aclose()

    async def _claim(self, limit: int) -> list[Run]:
        now = utcnow()
        async with self.services.db.sessions() as db:
            runs = (
                await db.scalars(
                    select(Run)
                    .where(
                        or_(
                            Run.status == "queued",
                            (Run.status == "running")
                            & (Run.lease_expires_at < now),
                        )
                    )
                    .order_by(Run.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for run in runs:
                run.status, run.lease_owner = "running", self.owner
                run.lease_expires_at = now + timedelta(
                    seconds=self.settings.run_lease_seconds
                )
                run.attempts += 1
            await db.commit()
        return list(runs)

    async def _heartbeat(self, run_id: str, task: asyncio.Task) -> None:
        """Renew the lease; stop the turn once it may have run out.

        A failed renewal is retried at the next beat. When none has worked
        for two thirds of the lease, another pod may claim the run soon, so
        this turn stops rather than run twice.
        """
        lease = self.settings.run_lease_seconds
        renewed = monotonic()
        while True:
            await asyncio.sleep(lease / 3)
            try:
                row = await self._renew(run_id)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - retried at the next beat
                log.warning("run_heartbeat_failed run_id=%s", run_id)
                if monotonic() - renewed >= lease * 2 / 3:
                    log.error("run_lease_unrenewed run_id=%s", run_id)
                    task.cancel()
                    return
                continue
            renewed = monotonic()
            if row is None or row.cancel_requested:
                task.cancel()  # lease lost or user cancelled
                return

    async def _renew(self, run_id: str) -> Any:
        async with self.services.db.sessions() as db:
            result = await db.execute(
                update(Run)
                .where(
                    Run.id == run_id,
                    Run.lease_owner == self.owner,
                    Run.status == "running",
                )
                .values(
                    lease_expires_at=utcnow()
                    + timedelta(seconds=self.settings.run_lease_seconds)
                )
                .returning(Run.cancel_requested)
            )
            row = result.first()
            await db.commit()
        return row

    async def _context(self, run: Run) -> RunContext:
        async with self.services.db.sessions() as db:
            session = await get_row(db, ChatSession, run.session_id)
            project = await get_row(db, Project, run.project_id)
        level = (
            session.code_level
            or project.code_level
            or self.settings.default_code_level
        )
        return RunContext(
            services=self.services,
            run_id=run.id,
            session_id=run.session_id,
            project_id=run.project_id,
            user_id=run.user_id,
            model=run.model,
            code_level=level,
            project_prompt=project.system_prompt,
            user_text=run.input["text"],
            user_content=run.input.get("content"),
        )

    async def _emit(self, run: Run, type: str, data: dict[str, Any]) -> None:
        await self.services.events.emit(run.session_id, run.id, type, data)

    async def _execute(self, run: Run) -> None:
        current = asyncio.current_task()
        assert current is not None  # called inside a task
        heartbeat = asyncio.create_task(self._heartbeat(run.id, current))
        try:
            if run.cancel_requested:
                raise asyncio.CancelledError
            # attempts counts claims since the last pause: a run that keeps
            # failing before it pauses (a crash, a deleted session) stops
            if run.attempts > self.settings.run_max_attempts:
                raise TooManyAttempts(
                    f"{run.attempts - 1} attempts ended without a result"
                )
            ctx = await self._context(run)
            await self._emit(run, "run_status", {"status": "running"})
            result = await self.graphs.run_turn(ctx, run.resume)
            if result.interrupt:
                await self._wait(run, result.interrupt)
            else:
                await self._finish(run, "succeeded", answer=result.answer)
        except asyncio.CancelledError:
            if await self._cancel_requested(run.id):
                await self._finish(run, "cancelled")
                await self._cancel_executor(run.id)
            # otherwise lease lost or shutdown: the next owner continues from
            # the checkpoint
        except LeaseLost:
            log.warning("run_lease_lost run_id=%s", run.id)
        except Exception as exc:  # noqa: BLE001
            log.exception("run_failed run_id=%s", run.id)
            await self._finish(
                run, "failed", error=f"{type(exc).__name__}: {exc}"
            )
        finally:
            heartbeat.cancel()

    async def _cancel_executor(self, run_id: str) -> None:
        """Stop executor work this turn already sent (cancel while running).

        The executor cancels the whole execution; the next turn starts a new
        kernel. Already finished executions just refuse the cancel.
        """
        async with self.services.db.sessions() as db:
            execution_id = await db.scalar(
                select(CodeSource.execution_id)
                .where(
                    CodeSource.run_id == run_id,
                    CodeSource.execution_id.is_not(None),
                )
                .order_by(CodeSource.created_at.desc())
                .limit(1)
            )
        if not execution_id:
            return
        await cancel_execution(
            self.services,
            execution_id,
            key=f"cancel:{run_id}",
            reason="사용자 취소",
        )

    async def _cancel_requested(self, run_id: str) -> bool:
        async with self.services.db.sessions() as db:
            return bool(
                await db.scalar(
                    select(Run.cancel_requested).where(Run.id == run_id)
                )
            )

    async def _wait(self, run: Run, interrupt: dict[str, Any]) -> None:
        value = interrupt["value"]
        # the pause contract readers rely on (RunRead.waiting, hitl_request)
        _PAUSE.validate_python({"interrupt_id": interrupt["id"], **value})
        if value.get("type") == "executor_wait":
            waiting = {
                "kind": "executor",
                "interrupt_id": interrupt["id"],
                **value,
            }
            async with self.services.db.sessions() as db:
                owned = await get_row(db, Run, run.id, lock=True)
                if owned.lease_owner != self.owner:
                    raise LeaseLost(run.id)
                if owned.cancel_requested:  # cancelled while it was running
                    raise asyncio.CancelledError
                event = await self._arrived_event(db, waiting)
                if event:  # the executor finished before we started waiting
                    owned.status, owned.waiting = "queued", None
                    owned.resume = {
                        "interrupt_id": interrupt["id"],
                        "value": event,
                    }
                else:
                    owned.status, owned.waiting, owned.resume = (
                        "waiting_executor",
                        waiting,
                        None,
                    )
                owned.lease_owner = owned.lease_expires_at = None
                owned.attempts = 0
                await db.commit()
            await self._emit(
                run,
                "run_status",
                {
                    "status": "waiting_executor",
                    "execution_id": value["execution_id"],
                    "operation_id": value["operation_id"],
                    "steps": value.get("steps", []),
                },
            )
            if event:
                await self.notify(run.id)
            return
        async with self.services.db.sessions() as db:
            parked = await db.execute(
                update(Run)
                .where(
                    Run.id == run.id,
                    Run.lease_owner == self.owner,
                    # cancel asked while it ran: finish it instead (the
                    # cancel route locks the row, so this cannot interleave)
                    Run.cancel_requested.is_(False),
                )
                .values(
                    status="waiting_input",
                    waiting={
                        "kind": "input",
                        "interrupt_id": interrupt["id"],
                        **value,
                    },
                    resume=None,
                    lease_owner=None,
                    lease_expires_at=None,
                    attempts=0,
                )
            )
            await db.commit()
        if not affected(parked):
            if await self._cancel_requested(run.id):
                raise asyncio.CancelledError
            raise LeaseLost(run.id)
        await self._emit(
            run, "hitl_request", {"interrupt_id": interrupt["id"], **value}
        )
        await self._emit(run, "run_status", {"status": "waiting_input"})

    @staticmethod
    async def _arrived_event(
        db, waiting: dict[str, Any]
    ) -> dict[str, Any] | None:
        rows = (
            await db.scalars(
                select(ExecutorInbox)
                .where(ExecutorInbox.execution_id == waiting["execution_id"])
                .order_by(ExecutorInbox.event_sequence)
            )
        ).all()
        for row in rows:
            if matches(waiting, row.event_type, row.payload):
                return {"event_type": row.event_type, "payload": row.payload}
        return None

    async def _finish(
        self,
        run: Run,
        status: str,
        answer: str | None = None,
        error: str | None = None,
    ) -> None:
        """End the run while this worker still holds it.

        A run whose lease another worker took over (or that ended
        otherwise) is left alone, events included.
        """
        async with self.services.db.sessions() as db:
            result = await db.execute(
                update(Run)
                .where(
                    Run.id == run.id,
                    Run.lease_owner == self.owner,
                    Run.status.notin_(TERMINAL),
                )
                .values(
                    status=status,
                    error=error,
                    waiting=None,
                    resume=None,
                    lease_owner=None,
                    lease_expires_at=None,
                    finished_at=utcnow(),
                )
            )
            finished = bool(affected(result))
            if finished:
                if answer:
                    artifacts = await db.scalars(
                        select(RunEvent.data)
                        .where(
                            RunEvent.run_id == run.id,
                            RunEvent.type == "artifact",
                        )
                        .order_by(RunEvent.id)
                    )
                    db.add(
                        Message(
                            session_id=run.session_id,
                            run_id=run.id,
                            role="assistant",
                            content=answer,
                            attachments=list(artifacts),
                        )
                    )
                await db.execute(
                    update(ChatSession)
                    .where(
                        ChatSession.id == run.session_id,
                        ChatSession.active_run_id == run.id,
                    )
                    .values(active_run_id=None)
                )
                if status == "succeeded" and answer:
                    # always, so a worker turned on later catches up
                    await mark_dirty(db, run.project_id, run.id)
            await db.commit()
        if not finished:
            log.warning("run_finish_skipped run_id=%s", run.id)
            return
        await self.services.forget_tool_effects(run.id)
        if answer:
            await self._emit(run, "message_final", {"content": answer})
            title_task = asyncio.create_task(self._auto_title(run, answer))
            self.background.add(title_task)
            title_task.add_done_callback(self.background.discard)
        if error:
            await self._emit(run, "run_error", {"message": error})
        await self._emit(run, "run_status", {"status": status})

    async def _auto_title(self, run: Run, answer: str) -> None:
        """Replace the first-message title with an LLM summary once.

        Never touches a user's rename.
        """
        async with self.services.db.sessions() as db:
            claimed = await db.execute(
                update(ChatSession)
                .where(
                    ChatSession.id == run.session_id,
                    ChatSession.title_source == "initial",
                )
                .values(title_source="auto")
            )
            await db.commit()
        if not affected(claimed):
            return
        try:
            title = await summarize_title(
                self.settings, run.model, run.input["text"], answer
            )
        except Exception:  # noqa: BLE001 - keep the first-message title
            log.warning("auto_title_failed session=%s", run.session_id)
            return
        if not title:
            return
        async with self.services.db.sessions() as db:
            renamed = await db.execute(
                update(ChatSession)
                .where(
                    ChatSession.id == run.session_id,
                    ChatSession.title_source == "auto",
                )
                .values(title=title)
            )
            await db.commit()
        if affected(renamed):
            await self._emit(run, "session_titled", {"title": title})

    async def progress(self, execution_id: str, event: dict[str, Any]) -> None:
        """Forward executor step progress.

        Sent to the session that is waiting on the execution.
        """
        async with self.services.db.sessions() as db:
            run = await db.scalar(
                select(Run).where(
                    Run.status == "waiting_executor",
                    Run.waiting["execution_id"].astext == execution_id,
                )
            )
        if run:
            payload = event["payload"]
            await self.services.events.emit(
                run.session_id,
                run.id,
                "execution_progress",
                {
                    "event_type": event["event_type"],
                    "status": payload.get("status"),
                    "step": payload.get("step"),
                    "error": payload.get("error"),
                    # step_handover_started / _completed: another executor
                    # worker takes over the step; the kernel keeps running
                    **{
                        k: payload[k]
                        for k in HANDOVER_FIELDS
                        if payload.get(k) is not None
                    },
                },
                # high volume; execution_completed is the durable summary
                durable=False,
            )
