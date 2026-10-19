"""Reports of successful BATCH executions.

The executor event consumer hands every ``execution.completed`` to
``enqueue``; a SUCCEEDED execution started by pr-batch (trigger BATCH) gets
one job, keyed ``batch-report:{execution_id}``. Failed runs get none.

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
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert

from agent.batch import BatchReportAgent, previous_runs, remember_run
from agent.context import BatchReportContext
from core.db import new_id, utcnow
from core.executor.client import trigger_type
from core.models import BatchReportJob, CodeSource
from core.notebook_links import lab_url
from core.services import Services

log = logging.getLogger(__name__)
ACTIVE = ("QUEUED", "COLLECTING", "GENERATING", "MATERIALIZING")


class NotReady(Exception):
    """The executor has not projected the notebook yet."""


async def enqueue(
    services: Services, execution_id: str, payload: dict[str, Any]
) -> str | None:
    """Queue the report of a finished execution if it gets one.

    The event's ``execution`` (trigger, context) decides. Events without it
    (executors before that field) are looked up, except executions this
    service sent itself (its code-source index knows them).
    """
    if payload.get("status") != "SUCCEEDED":
        return None
    execution = payload.get("execution") or {}
    if not trigger_type(execution):
        async with services.db.sessions() as db:
            ours = await db.scalar(
                select(CodeSource.id)
                .where(CodeSource.execution_id == execution_id)
                .limit(1)
            )
        if ours:
            return None
        execution = await services.executor.get(execution_id)
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
                batch_run_id=context.get("task_id"),
                execution={
                    "trigger": execution.get("trigger") or {"type": "BATCH"},
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
        return await enqueue(self.services, execution_id, payload)

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
        async with self.services.db.sessions() as db:
            job = await db.get(BatchReportJob, job_id)
            for key, value in values.items():
                setattr(job, key, value)
            await db.commit()

    async def _heartbeat(self, job_id: str) -> None:
        """Keeps the lease while the agent works (minutes, not seconds)."""
        while True:
            await asyncio.sleep(self.lease_seconds / 3)
            async with self.services.db.sessions() as db:
                await db.execute(
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

    async def _emit(self, job_id: str, type: str, data: dict) -> None:
        await self.services.events.emit_report(job_id, type, data)

    async def _process(self, job: BatchReportJob) -> None:
        heartbeat = asyncio.create_task(self._heartbeat(job.id))
        try:
            await self._run(job)
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
        known = (job.execution or {}).get("metadata") or {}
        metadata = execution.get("metadata") or known
        if job.batch_id is None and metadata.get("batch_id"):
            job.batch_id = metadata["batch_id"]
            await self._set(job.id, batch_id=job.batch_id)
        return {**execution, "metadata": metadata}

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
        artifact = await executor.create_report(
            job.execution_id,
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
        notebook = next(
            (
                a
                for a in await executor.artifacts(job.execution_id)
                if a["type"] == "NOTEBOOK"
            ),
            None,
        )
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
