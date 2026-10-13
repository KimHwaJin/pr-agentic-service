"""Runs agent turns from the ``runs`` table on any pod.

A run is claimed with FOR UPDATE SKIP LOCKED and a lease. While it waits for the user or the
executor it holds no pod resources (status waiting_*). If a pod dies, the lease expires and another
pod continues from the LangGraph checkpoint. Every state change is guarded by the lease owner.
"""

import asyncio
import contextlib
import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select, update

from agent.context import RunContext
from agent.graph import AgentGraphs
from core.db import utcnow
from core.events import runs_wake_channel
from core.models import ChatSession, ExecutorInbox, Message, Project, Run, RunEvent, User
from core.services import Services
from worker.executor_events import matches

log = logging.getLogger(__name__)
TERMINAL = {"succeeded", "failed", "cancelled"}


class LeaseLost(Exception):
    pass


class RunScheduler:
    def __init__(self, services: Services, graphs: AgentGraphs, owner: str):
        self.services, self.graphs, self.owner = services, graphs, owner
        self.settings = services.settings
        self.tasks: set[asyncio.Task] = set()
        self.accepting = True
        self._wake = asyncio.Event()

    async def notify(self, run_id: str | None = None) -> None:
        await self.services.events.wake_runs(run_id or "")

    async def run_forever(self) -> None:
        listener = asyncio.create_task(self._listen())
        try:
            while self.accepting:
                self._wake.clear()  # before claiming, so a wake during the claim is not lost
                free = self.settings.run_concurrency - len(self.tasks)
                runs = await self._claim(free) if free > 0 else []
                for run in runs:
                    task = asyncio.create_task(self._execute(run))
                    self.tasks.add(task)
                    task.add_done_callback(self._task_done)
                if len(runs) == free and free > 0:
                    continue  # the queue may hold more work
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), self.settings.run_poll_seconds)
        finally:
            listener.cancel()

    def _task_done(self, task: asyncio.Task) -> None:
        self.tasks.discard(task)
        self._wake.set()  # a slot is free: claim queued work now, not at the next poll

    async def drain(self, timeout: float) -> None:
        """Graceful shutdown: stop claiming, let running turns finish, then release leases."""
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
                .values(status="queued", lease_owner=None, lease_expires_at=None)
            )
            await db.commit()

    async def _listen(self) -> None:
        pubsub = self.services.redis.pubsub()
        await pubsub.subscribe(runs_wake_channel(self.settings.redis_namespace))
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    self._wake.set()
        finally:
            await pubsub.aclose()

    async def _claim(self, limit: int) -> list[Run]:
        now = utcnow()
        async with self.services.db.sessions() as db:
            runs = (
                await db.scalars(
                    select(Run)
                    .where(or_(Run.status == "queued", (Run.status == "running") & (Run.lease_expires_at < now)))
                    .order_by(Run.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for run in runs:
                run.status, run.lease_owner = "running", self.owner
                run.lease_expires_at = now + timedelta(seconds=self.settings.run_lease_seconds)
                run.attempts += 1
            await db.commit()
        return list(runs)

    async def _heartbeat(self, run_id: str, task: asyncio.Task) -> None:
        while True:
            await asyncio.sleep(self.settings.run_lease_seconds / 3)
            async with self.services.db.sessions() as db:
                result = await db.execute(
                    update(Run)
                    .where(Run.id == run_id, Run.lease_owner == self.owner, Run.status == "running")
                    .values(lease_expires_at=utcnow() + timedelta(seconds=self.settings.run_lease_seconds))
                    .returning(Run.cancel_requested)
                )
                row = result.first()
                await db.commit()
            if row is None or row.cancel_requested:
                task.cancel()  # lease lost or user cancelled
                return

    async def _context(self, run: Run) -> RunContext:
        async with self.services.db.sessions() as db:
            session = await db.get(ChatSession, run.session_id)
            project = await db.get(Project, run.project_id)
            user = await db.get(User, run.user_id)
        level = session.code_level or project.code_level or self.settings.default_code_level
        return RunContext(
            services=self.services,
            run_id=run.id,
            session_id=run.session_id,
            project_id=run.project_id,
            user_id=run.user_id,
            employee_id=user.employee_id,
            model_alias=run.model_alias,
            code_level=level,
            project_prompt=project.system_prompt,
            user_text=run.input["text"],
        )

    async def _execute(self, run: Run) -> None:
        ctx = await self._context(run)
        current = asyncio.current_task()
        heartbeat = asyncio.create_task(self._heartbeat(run.id, current))
        try:
            if run.cancel_requested:
                raise asyncio.CancelledError
            await ctx.emit("run_status", {"status": "running"})
            result = await self.graphs.run_turn(ctx, run.resume)
            if result.interrupt:
                await self._wait(run, ctx, result.interrupt)
            else:
                await self._finish(run, ctx, "succeeded", answer=result.answer)
        except asyncio.CancelledError:
            if await self._cancel_requested(run.id):
                await self._finish(run, ctx, "cancelled")
            # otherwise lease lost or shutdown: the next owner continues from the checkpoint
        except LeaseLost:
            log.warning("run_lease_lost run_id=%s", run.id)
        except Exception as exc:  # noqa: BLE001
            log.exception("run_failed run_id=%s", run.id)
            await self._finish(run, ctx, "failed", error=f"{type(exc).__name__}: {exc}")
        finally:
            heartbeat.cancel()

    async def _cancel_requested(self, run_id: str) -> bool:
        async with self.services.db.sessions() as db:
            return bool(await db.scalar(select(Run.cancel_requested).where(Run.id == run_id)))

    async def _wait(self, run: Run, ctx: RunContext, interrupt: dict[str, Any]) -> None:
        value = interrupt["value"]
        if value.get("type") == "executor_wait":
            waiting = {"kind": "executor", "interrupt_id": interrupt["id"], **value}
            async with self.services.db.sessions() as db:
                owned = await db.get(Run, run.id, with_for_update=True)
                if owned.lease_owner != self.owner:
                    raise LeaseLost(run.id)
                event = await self._arrived_event(db, waiting)
                if event:  # the executor finished before we started waiting
                    owned.status, owned.waiting = "queued", None
                    owned.resume = {"interrupt_id": interrupt["id"], "value": event}
                else:
                    owned.status, owned.waiting, owned.resume = "waiting_executor", waiting, None
                owned.lease_owner = owned.lease_expires_at = None
                await db.commit()
            await ctx.emit(
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
            await db.execute(
                update(Run)
                .where(Run.id == run.id, Run.lease_owner == self.owner)
                .values(
                    status="waiting_input",
                    waiting={"kind": "input", "interrupt_id": interrupt["id"], **value},
                    resume=None,
                    lease_owner=None,
                    lease_expires_at=None,
                )
            )
            await db.commit()
        await ctx.emit("hitl_request", {"interrupt_id": interrupt["id"], **value})
        await ctx.emit("run_status", {"status": "waiting_input"})

    @staticmethod
    async def _arrived_event(db, waiting: dict[str, Any]) -> dict[str, Any] | None:
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
        self, run: Run, ctx: RunContext, status: str, answer: str | None = None, error: str | None = None
    ) -> None:
        async with self.services.db.sessions() as db:
            result = await db.execute(
                update(Run)
                .where(Run.id == run.id, Run.status.notin_(TERMINAL))
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
            if result.rowcount:
                if answer:
                    artifacts = await db.scalars(
                        select(RunEvent.data)
                        .where(RunEvent.run_id == run.id, RunEvent.type == "artifact")
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
                    .where(ChatSession.id == run.session_id, ChatSession.active_run_id == run.id)
                    .values(active_run_id=None)
                )
            await db.commit()
        await self._forget_tool_effects(run.id)
        if answer:
            await ctx.emit("message_final", {"content": answer})
        if error:
            await ctx.emit("run_error", {"message": error})
        await ctx.emit("run_status", {"status": status})

    async def _forget_tool_effects(self, run_id: str) -> None:
        """Replay guards (agent.tools.analysis._once) are only needed while the run is alive."""
        store = self.services.memory.store
        namespace = ("tool_effects", run_id)
        for item in await store.asearch(namespace, limit=1000):
            await store.adelete(namespace, item.key)

    async def progress(self, execution_id: str, event: dict[str, Any]) -> None:
        """Forward executor step progress to the session that is waiting on the execution."""
        async with self.services.db.sessions() as db:
            run = await db.scalar(
                select(Run).where(Run.status == "waiting_executor", Run.waiting["execution_id"].astext == execution_id)
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
                },
                durable=False,  # high volume; execution_completed is the durable summary
            )
