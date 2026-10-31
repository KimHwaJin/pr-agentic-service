"""Reports of successful BATCH executions.

The executor event consumer hands every ``execution.completed`` to
``enqueue``; a SUCCEEDED execution started by pr-batch (trigger BATCH) gets
one job, keyed ``batch-report:{execution_id}``. Failed runs get none.
An execution whose event never reached us (worker down past the stream's
retention, Redis lost it) is found by ``BatchReportRecovery`` instead.

QUEUED -> COLLECTING -> GENERATING -> MATERIALIZING -> SUCCEEDED | FAILED.

* COLLECTING waits until the executor has projected the notebook. A job
  that is not ready goes back to the table with a short "not before" lease
  instead of holding the worker, until ``batch_report_collect_timeout``.
* GENERATING runs the batch report agent (agent.batch) with the summaries
  of the batch's earlier runs.
* MATERIALIZING stores the report as an executor artifact appended to the
  notebook, then remembers this run for the next one.

A retry queues the job again; a generated report is reused so only
materialization repeats. Progress goes to the job's event stream in the
chat event format (``EventBus.emit_report``).
"""

import asyncio
import contextlib
import logging
from datetime import datetime, timedelta
from time import monotonic
from typing import Any

from sqlalchemy import or_, select, text, update
from sqlalchemy.dialects.postgresql import insert

from agent.batch import BatchReportAgent, previous_runs, remember_run
from agent.context import BatchReportContext
from core.db import affected, new_id, utcnow
from core.executor.client import ExecutorError, Identity, trigger_type
from core.models import BatchReportJob
from core.notebook_links import lab_url
from core.services import Services

log = logging.getLogger(__name__)
ACTIVE = ("QUEUED", "COLLECTING", "GENERATING", "MATERIALIZING")
RECOVERY_LOCK = 7_202_510  # pg advisory lock: one pod sweeps at a time


class NotReady(Exception):
    """The executor has not projected the notebook yet."""


class LeaseLost(Exception):
    """Another pod holds the job now (this lease expired): stop writing."""


async def enqueue(services: Services, execution_id: str) -> str | None:
    """Queue the report of a finished execution if it gets one.

    Executor events can be forged (no Redis ACL), so the event only says
    which execution to look at: the execution as the executor answers it
    decides. Our key reads only our tenant's executions, so one that is
    found is a run of a batch registered through us (pr-batch submitted
    it; it is not in our tables).
    """
    try:
        execution = await services.executor.get(execution_id)
    except ExecutorError as exc:
        if exc.status != 404:
            raise
        log.warning(
            "batch_report_unknown_execution execution=%s", execution_id
        )
        return None
    if (execution.get("state") or {}).get("status") != "SUCCEEDED":
        return None
    if trigger_type(execution) != "BATCH":
        return None
    context = execution.get("context") or {}
    metadata = execution.get("metadata") or {}
    if not context.get("user_id"):
        log.warning("batch_report_without_owner execution=%s", execution_id)
        return None
    now = utcnow()
    async with services.db.sessions() as db:
        job_id = await db.scalar(
            insert(BatchReportJob)
            .values(
                id=new_id(),
                idempotency_key=f"batch-report:{execution_id}",
                owner_id=context["user_id"],
                execution_id=execution_id,
                batch_id=metadata.get("batch_id"),
                batch_run_id=metadata.get("run_id"),
                execution={
                    "trigger": execution["trigger"],
                    "context": context,
                    "metadata": metadata,
                },
                state="QUEUED",
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(BatchReportJob.id)
        )
        await db.commit()
    if job_id:
        await services.events.emit_report(
            job_id, "run_status", {"status": "queued"}
        )
    return job_id


class BatchReportRecovery:
    """Jobs for successful BATCH executions the event stream never brought.

    Every ``interval`` it lists our tenant's SUCCEEDED BATCH executions of
    the lookback that finished at least one interval ago (the stream had
    its chance) and queues those without a job. ``enqueue`` is idempotent,
    so a late event or a second pod changes nothing.
    """

    def __init__(self, services: Services):
        settings = services.settings
        self.services = services
        self.interval = settings.batch_report_recovery_interval_seconds
        self.lookback = timedelta(
            days=settings.batch_report_recovery_lookback_days
        )

    async def run_forever(self) -> None:
        while True:
            try:
                await self.sweep()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - try again next round
                log.exception("batch_report_recovery_error")
            await asyncio.sleep(self.interval)

    async def sweep(self) -> list[str]:
        async with self.services.db.sessions() as lock:
            if not await lock.scalar(
                text("SELECT pg_try_advisory_xact_lock(:k)"),
                {"k": RECOVERY_LOCK},
            ):
                return []  # another pod is sweeping
            return await self._recover()

    async def _recover(self) -> list[str]:
        now = utcnow()
        executions = await self.services.executor.executions(
            now - self.lookback,
            trigger_type="BATCH",
            status="SUCCEEDED",
        )
        settled = now - timedelta(seconds=self.interval)
        due = [
            e
            for e in executions
            if (finished := (e.get("lifecycle") or {}).get("finished_at"))
            and datetime.fromisoformat(finished) < settled
        ]
        if not due:
            return []
        async with self.services.db.sessions() as db:
            known = set(
                await db.scalars(
                    select(BatchReportJob.execution_id).where(
                        BatchReportJob.execution_id.in_(
                            [e["execution_id"] for e in due]
                        )
                    )
                )
            )
        recovered = []
        for execution in due:
            execution_id = execution["execution_id"]
            if execution_id in known:
                continue
            job_id = await enqueue(self.services, execution_id)
            if job_id:
                log.warning(
                    "batch_report_recovered execution=%s job=%s",
                    execution_id,
                    job_id,
                )
                recovered.append(job_id)
        return recovered


class BatchReportWorker:
    def __init__(
        self, services: Services, owner: str, lease_seconds: int = 300
    ):
        self.services, self.owner, self.lease_seconds = (
            services,
            owner,
            lease_seconds,
        )
        self.settings = services.settings
        self.agent = BatchReportAgent(services.settings)

    async def enqueue(
        self, execution_id: str, payload: dict[str, Any]
    ) -> str | None:
        """``on_completed`` of the event consumer; the payload is not used."""
        if payload.get("status") not in (None, "SUCCEEDED"):
            return None  # a failed run gets no report; skip the lookup
        return await enqueue(self.services, execution_id)

    async def run_forever(self) -> None:
        while True:
            try:
                job = await self._claim()
                if job is None:
                    await asyncio.sleep(5)
                    continue
                await self._process(job)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("batch_report_worker_error")
                await asyncio.sleep(5)

    async def _claim(self) -> BatchReportJob | None:
        now = utcnow()
        async with self.services.db.sessions() as db:
            job = await db.scalar(
                select(BatchReportJob)
                .where(
                    BatchReportJob.state.in_(ACTIVE),
                    or_(
                        BatchReportJob.lease_expires_at.is_(None),
                        BatchReportJob.lease_expires_at < now,
                    ),
                )
                .order_by(BatchReportJob.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if job:
                job.lease_owner, job.lease_expires_at = (
                    self.owner,
                    now + timedelta(seconds=self.lease_seconds),
                )
                await db.commit()
            return job

    async def _set(self, job_id: str, **values) -> None:
        """Writes the job only while this worker holds its lease."""
        async with self.services.db.sessions() as db:
            result = await db.execute(
                update(BatchReportJob)
                .where(
                    BatchReportJob.id == job_id,
                    BatchReportJob.lease_owner == self.owner,
                )
                .values(**values)
            )
            await db.commit()
        if not affected(result):
            raise LeaseLost(job_id)

    async def _renew(self, job_id: str) -> bool:
        async with self.services.db.sessions() as db:
            result = await db.execute(
                update(BatchReportJob)
                .where(
                    BatchReportJob.id == job_id,
                    BatchReportJob.lease_owner == self.owner,
                )
                .values(
                    lease_expires_at=utcnow()
                    + timedelta(seconds=self.lease_seconds)
                )
            )
            await db.commit()
        return bool(affected(result))

    async def _heartbeat(self, job_id: str, work: asyncio.Task) -> None:
        """Keeps the lease while the agent works (minutes, not seconds).

        Stops the work once the lease is someone else's, or could not be
        renewed for 2/3 of it (the database is unreachable): another pod
        may claim the job when it expires.
        """
        renewed = monotonic()
        while True:
            await asyncio.sleep(self.lease_seconds / 3)
            try:
                held = await self._renew(job_id)
            except Exception:  # noqa: BLE001 - retried on the next beat
                log.warning("batch_report_heartbeat_failed job=%s", job_id)
                if monotonic() - renewed < self.lease_seconds * 2 / 3:
                    continue
                held = False
            if not held:
                log.warning("batch_report_lease_lost job=%s", job_id)
                work.cancel()
                return
            renewed = monotonic()

    async def _emit(self, job_id: str, type: str, data: dict) -> None:
        await self.services.events.emit_report(job_id, type, data)

    async def _process(self, job: BatchReportJob) -> None:
        work = asyncio.create_task(self._run(job))
        heartbeat = asyncio.create_task(self._heartbeat(job.id, work))
        try:
            await work
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise  # shutdown: the lease runs out, another pod resumes
            log.warning("batch_report_stopped job=%s (lease lost)", job.id)
        except LeaseLost:
            log.warning("batch_report_stopped job=%s (lease lost)", job.id)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

    async def _run(self, job: BatchReportJob) -> None:
        claimed = job.state  # COLLECTING: back from a wait for the notebook
        stage = claimed
        if claimed != "COLLECTING":
            await self._emit(job.id, "run_status", {"status": "running"})
        try:
            if job.markdown is None:
                stage = "COLLECTING"
                since = job.collecting_since or utcnow()
                await self._set(job.id, state=stage, collecting_since=since)
                execution = await self._collect(job, since)
                stage = "GENERATING"
                await self._set(job.id, state=stage)
                report = await self._generate(job, execution)
                await self._set(job.id, **report)
            else:
                report = {
                    "title": job.title,
                    "markdown": job.markdown,
                    "summary": job.summary,
                }
            stage = "MATERIALIZING"
            await self._set(job.id, state=stage)
            await self._materialize(job, report)
        except NotReady:
            await self._set(
                job.id,
                lease_owner=None,
                lease_expires_at=utcnow()
                + timedelta(seconds=self.settings.batch_report_poll_seconds),
            )
            if claimed != "COLLECTING":  # the first wait says so once
                await self._emit(
                    job.id,
                    "run_status",
                    {
                        "status": "waiting_executor",
                        "execution_id": job.execution_id,
                        "steps": ["notebook"],
                    },
                )
        except LeaseLost:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("batch_report_failed job=%s stage=%s", job.id, stage)
            error = f"{type(exc).__name__}: {exc}"[:2000]
            await self._set(
                job.id,
                state="FAILED",
                failed_stage=stage,
                error=error,
                lease_owner=None,
                lease_expires_at=None,
                finished_at=utcnow(),
            )
            await self._emit(job.id, "run_error", {"message": error})
            await self._emit(job.id, "run_status", {"status": "failed"})

    async def _collect(
        self, job: BatchReportJob, since: datetime
    ) -> dict[str, Any]:
        """The execution, once the executor has projected its notebook."""
        execution = await self.services.executor.get(job.execution_id)
        status = execution["state"]["status"]
        if status != "SUCCEEDED":
            raise RuntimeError(
                f"execution is {status}; reports need a SUCCEEDED execution"
            )
        projection = (execution.get("workspace") or {}).get(
            "notebook_projection"
        ) or {}
        if projection.get("status") == "FAILED":
            raise RuntimeError(
                "notebook projection failed: "
                f"{projection.get('error_message')}"
            )
        if projection.get("status") not in (None, "SUCCEEDED"):
            timeout = self.settings.batch_report_collect_timeout_seconds
            if utcnow() - since > timedelta(seconds=timeout):
                raise TimeoutError(
                    f"notebook not projected after {timeout}s "
                    f"(status {projection.get('status')})"
                )
            raise NotReady
        return execution

    async def _generate(
        self, job: BatchReportJob, execution: dict[str, Any]
    ) -> dict[str, Any]:
        history = await previous_runs(
            self.services.memory.store,
            job.batch_id,
            job.execution_id,
            self.settings.batch_report_memory_runs,
        )
        ctx = BatchReportContext(
            services=self.services,
            job_id=job.id,
            execution_id=job.execution_id,
            batch_id=job.batch_id,
            model=self.settings.batch_report_model
            or self.settings.default_model.name,
        )
        return await self.agent.write(ctx, execution, history)

    async def _materialize(
        self, job: BatchReportJob, report: dict[str, Any]
    ) -> None:
        executor = self.services.executor
        title = report["title"] or "배치 실행 리포트"
        context = (job.execution or {}).get("context") or {}
        artifact = await executor.create_report(
            job.execution_id,
            who=Identity(
                user_id=job.owner_id,
                project_id=context.get("project_id"),
                session_id=context.get("session_id"),
            ),
            idempotency_key=f"batch-report:{job.id}",
            markdown=report["markdown"],
            name=f"batch-{job.batch_run_id or job.execution_id}-report.md",
            metadata={
                "title": title,
                "batch_id": job.batch_id,
                "batch_run_id": job.batch_run_id,
                "report_job_id": job.id,
            },
        )
        try:
            await remember_run(
                self.services.memory.store,
                job.batch_id,
                job.execution_id,
                {
                    "execution_id": job.execution_id,
                    "batch_run_id": job.batch_run_id,
                    "report_job_id": job.id,
                    "artifact_id": artifact["artifact_id"],
                    "title": title,
                    "summary": report["summary"] or "",
                    "finished_at": utcnow().isoformat(),
                },
            )
        except Exception:  # noqa: BLE001 - the report itself is done
            log.exception("batch_memory_write_failed job=%s", job.id)
        await self._set(
            job.id,
            state="SUCCEEDED",
            artifact_id=artifact["artifact_id"],
            failed_stage=None,
            error=None,
            lease_owner=None,
            lease_expires_at=None,
            finished_at=utcnow(),
        )
        await self._emit(
            job.id,
            "artifact",
            {
                "kind": "report",
                "artifact_id": artifact["artifact_id"],
                "title": title,
            },
        )
        notebook = await executor.notebook(job.execution_id)
        if notebook:
            await self._emit(
                job.id,
                "artifact",
                {
                    "kind": "notebook",
                    "artifact_id": notebook["artifact_id"],
                    "title": f"{title} 노트북",
                    "lab_url": lab_url(
                        self.settings,
                        notebook["storage"].get("relative_path"),
                        job.owner_id,
                    ),
                },
            )
        await self._emit(
            job.id, "message_final", {"content": report["markdown"]}
        )
        await self._emit(job.id, "run_status", {"status": "succeeded"})
