"""pr-batch report jobs.

QUEUED -> COLLECTING -> GENERATING -> MATERIALIZING -> SUCCEEDED | FAILED.

A retry resumes the failed stage; a generated Markdown is reused so only
materialization repeats.
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import or_, select

from agent.reporter import generate_batch_report
from core.db import utcnow
from core.models import BatchReportJob
from core.services import Services

log = logging.getLogger(__name__)
ACTIVE = ("QUEUED", "COLLECTING", "GENERATING", "MATERIALIZING")


class BatchReportWorker:
    def __init__(
        self, services: Services, owner: str, lease_seconds: int = 300
    ):
        self.services, self.owner, self.lease_seconds = (
            services,
            owner,
            lease_seconds,
        )

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

    async def _process(self, job: BatchReportJob) -> None:
        executor = self.services.executor
        stage = job.state
        try:
            if job.markdown is None:
                stage = "COLLECTING"
                await self._set(job.id, state=stage)
                status = (await executor.get(job.execution_id))["state"][
                    "status"
                ]
                if status != "SUCCEEDED":
                    raise RuntimeError(
                        f"execution is {status}; "
                        "reports need a SUCCEEDED execution"
                    )
                stage = "GENERATING"
                await self._set(job.id, state=stage)
                markdown = await generate_batch_report(
                    self.services,
                    job.execution_id,
                    job.request.get("options", {}),
                )
                await self._set(job.id, markdown=markdown)
            else:
                markdown = job.markdown
            stage = "MATERIALIZING"
            await self._set(job.id, state=stage)
            artifact = await executor.create_report(
                job.execution_id,
                idempotency_key=f"batch-report:{job.id}",
                markdown=markdown,
                name=f"batch-{job.batch_run_id}-report.md",
                metadata={
                    "batch_run_id": job.batch_run_id,
                    "report_job_id": job.id,
                },
            )
            await self._set(
                job.id,
                state="SUCCEEDED",
                artifact_id=artifact["artifact_id"],
                failed_stage=None,
                error=None,
                lease_owner=None,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("batch_report_failed job=%s stage=%s", job.id, stage)
            await self._set(
                job.id,
                state="FAILED",
                failed_stage=stage,
                error=f"{type(exc).__name__}: {exc}"[:2000],
                lease_owner=None,
            )
