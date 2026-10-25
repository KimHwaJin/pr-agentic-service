"""Reports of the user's batch runs (worker.batch_reports).

A job exists per successful BATCH execution and belongs to the execution's
user. Its progress events have the chat run event format (``run_id`` is the
report id), so the chat components draw a report screen too. Separate from
``/batch/*``, which relays to pr-batch.
"""

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from api_service import pagination
from api_service.deps import ServicesDep, UserDep
from api_service.schemas.batch import (
    BatchReportDetail,
    BatchReportEvents,
    BatchReportPage,
)
from api_service.sse import event_stream
from core.db import get_row
from core.models import BatchReportEvent, BatchReportJob, User
from core.services import Services

router = APIRouter(prefix="/batch-reports", tags=["batch-reports"])


async def _report_for(
    services: Services, user: User, report_id: str
) -> BatchReportJob:
    async with services.db.sessions() as db:
        job = await db.get(BatchReportJob, report_id)
    if job is None or job.owner_id != user.id:
        raise HTTPException(404, "Batch report not found.")
    return job


def _detail(job: BatchReportJob, user: User) -> BatchReportDetail:
    return BatchReportDetail.model_validate(
        {
            **{
                name: getattr(job, name)
                for name in BatchReportDetail.model_fields
                if name != "owner"
            },
            "owner": user,
        }
    )


@router.get("", response_model=BatchReportPage)
async def list_reports(
    services: ServicesDep,
    user: UserDep,
    batch_id: str | None = None,
    execution_id: str | None = None,
    status: str | None = None,
    limit: int = pagination.Limit,
    cursor: str | None = None,
):
    """The user's report jobs, newest first.

    ``status`` filters by state, e.g. ``FAILED`` or ``QUEUED,GENERATING``.
    """
    query = select(BatchReportJob).where(
        BatchReportJob.owner_id == user.id,
        pagination.older_than(
            BatchReportJob.created_at, BatchReportJob.id, cursor
        ),
    )
    if batch_id:
        query = query.where(BatchReportJob.batch_id == batch_id)
    if execution_id:
        query = query.where(BatchReportJob.execution_id == execution_id)
    if status:
        states = [s.strip().upper() for s in status.split(",") if s.strip()]
        query = query.where(BatchReportJob.state.in_(states))
    async with services.db.sessions() as db:
        rows = (
            await db.scalars(
                query.order_by(
                    BatchReportJob.created_at.desc(), BatchReportJob.id.desc()
                ).limit(limit + 1)
            )
        ).all()
    page = rows[:limit]
    return BatchReportPage(
        items=page,
        next_cursor=pagination.encode(page[-1].created_at, page[-1].id)
        if len(rows) > limit
        else None,
    )


@router.get("/{report_id}", response_model=BatchReportDetail)
async def get_report(report_id: str, services: ServicesDep, user: UserDep):
    return _detail(await _report_for(services, user, report_id), user)


@router.get("/{report_id}/events", response_model=BatchReportEvents)
async def report_events(
    report_id: str,
    services: ServicesDep,
    user: UserDep,
    types: str | None = None,
):
    """Durable events of the job, in order (``types`` filters).

    Token deltas and activity are live-only (``/stream``).
    """
    job = await _report_for(services, user, report_id)
    query = select(BatchReportEvent).where(
        BatchReportEvent.job_id == report_id
    )
    if types:
        query = query.where(
            BatchReportEvent.type.in_(
                [t.strip() for t in types.split(",") if t.strip()]
            )
        )
    async with services.db.sessions() as db:
        rows = (
            await db.scalars(query.order_by(BatchReportEvent.id).limit(5000))
        ).all()
    return BatchReportEvents.model_validate(
        {"report_id": report_id, "state": job.state, "items": rows}
    )


@router.get("/{report_id}/stream")
async def report_stream(
    report_id: str,
    request: Request,
    services: ServicesDep,
    user: UserDep,
    after: int | None = None,
):
    """SSE of the job: its stored events, then live ones.

    Resume with the ``Last-Event-ID`` header (or ``?after=``).
    """
    await _report_for(services, user, report_id)
    cursor = request.headers.get("last-event-id") or after
    return event_stream(
        request,
        services.events,
        services.events.report_channel(report_id),
        lambda after_id: services.events.report_history(report_id, after_id),
        cursor,
    )


@router.post(
    "/{report_id}/retry", response_model=BatchReportDetail, status_code=202
)
async def retry_report(report_id: str, services: ServicesDep, user: UserDep):
    """Queue a failed job again.

    A report already written is kept; only saving it repeats.
    """
    await _report_for(services, user, report_id)
    async with services.db.sessions() as db:
        job = await get_row(db, BatchReportJob, report_id, lock=True)
        if job.state != "FAILED":
            raise HTTPException(409, "Only failed reports can be retried.")
        job.state = "QUEUED"
        job.error = job.lease_owner = job.lease_expires_at = None
        job.collecting_since = job.finished_at = None
        await db.commit()
    await services.events.emit_report(
        report_id, "run_status", {"status": "queued"}
    )
    return _detail(job, user)
