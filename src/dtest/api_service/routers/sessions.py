from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import delete, select, update

from src.dtest.api_service import pagination
from src.dtest.api_service.deps import (
    ServicesDep,
    UserDep,
    project_for,
    session_for,
)
from src.dtest.api_service.errors import ApiError
from src.dtest.api_service.schemas.sessions import (
    ChatSessionRead,
    MessagePage,
    RunCreate,
    RunEvents,
    RunPage,
    RunRead,
    RunStart,
    SessionCreate,
    SessionPage,
    SessionStart,
    SessionUpdate,
)
from src.dtest.api_service.services.access import execution_of_session
from src.dtest.api_service.services.runs import create_run
from src.dtest.api_service.sse import event_stream
from src.dtest.core.db import get_row, utcnow
from src.dtest.core.executor.client import ExecutorError
from src.dtest.core.models import (
    ChatSession,
    Message,
    Run,
    RunEvent,
    User,
)
from src.dtest.core.services import Services

router = APIRouter(tags=["sessions"])


@router.post(
    "/projects/{project_id}/sessions",
    response_model=SessionStart,
    status_code=201,
)
async def create_session(
    project_id: str, body: SessionCreate, services: ServicesDep, user: UserDep
):
    """Creates a session.

    With ``message`` the first turn starts immediately (login -> chat).
    """
    await project_for(services, user, project_id, write=True)
    if body.input is not None and services.settings.model(body.model) is None:
        raise ApiError(
            422,
            "unknown_model",
            "Unknown model.",
            models=[m.name for m in services.settings.models],
        )
    first = body.input.text if body.input else None
    title = body.title or (first[:40] if first else "새 대화")
    async with services.db.sessions() as db:
        session = ChatSession(
            project_id=project_id,
            user_id=user.id,
            title=title,
            title_source="user" if body.title else "initial",
            code_level=body.code_level,
        )
        db.add(session)
        await db.commit()
    run = None
    if body.input is not None:
        try:
            started = await create_run(
                services,
                user,
                session.id,
                RunCreate(input=body.input, model=body.model),
            )
        except ApiError:
            # the first turn was refused: do not leave an empty session
            async with services.db.sessions() as db:
                await db.execute(
                    delete(ChatSession).where(ChatSession.id == session.id)
                )
                await db.commit()
            raise
        run = started.run
    async with services.db.sessions() as db:
        session = await db.get(ChatSession, session.id)
    return SessionStart(
        session=ChatSessionRead.model_validate(session), run=run
    )


@router.get("/projects/{project_id}/sessions", response_model=SessionPage)
async def list_sessions(
    project_id: str,
    services: ServicesDep,
    user: UserDep,
    limit: int = pagination.Limit,
    cursor: str | None = None,
):
    """Most recently updated first."""
    await project_for(services, user, project_id)
    async with services.db.sessions() as db:
        rows = (
            await db.scalars(
                select(ChatSession)
                .where(
                    ChatSession.project_id == project_id,
                    ChatSession.deleted_at.is_(None),
                    pagination.older_than(
                        ChatSession.updated_at, ChatSession.id, cursor
                    ),
                )
                .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
                .limit(limit + 1)
            )
        ).all()
    page = rows[:limit]
    more = len(rows) > limit
    return SessionPage(
        items=page,
        next_cursor=pagination.encode(page[-1].updated_at, page[-1].id)
        if more
        else None,
    )


@router.get("/sessions/{session_id}", response_model=ChatSessionRead)
async def get_session(session_id: str, services: ServicesDep, user: UserDep):
    return await session_for(services, user, session_id)


@router.patch("/sessions/{session_id}", response_model=ChatSessionRead)
async def update_session(
    session_id: str, body: SessionUpdate, services: ServicesDep, user: UserDep
):
    await session_for(services, user, session_id, write=True)
    async with services.db.sessions() as db:
        session = await get_row(db, ChatSession, session_id)
        for key, value in body.changes(nullable={"code_level"}).items():
            setattr(session, key, value)
        if body.title is not None:
            session.title_source = "user"  # never auto-renamed again
        await db.commit()
        return session


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str, services: ServicesDep, user: UserDep
):
    session = await session_for(services, user, session_id, write=True)
    if session.active_run_id:
        raise HTTPException(409, "Cancel the running turn first.")
    async with services.db.sessions() as db:
        await db.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(deleted_at=utcnow())
        )
        await db.commit()
    # the agent's history of the session goes with it (thread = session)
    await services.checkpointer.adelete_thread(session_id)
    return Response(status_code=204)


@router.get("/sessions/{session_id}/messages", response_model=MessagePage)
async def list_messages(
    session_id: str,
    services: ServicesDep,
    user: UserDep,
    limit: int = pagination.Limit,
    cursor: str | None = None,
):
    """The latest ``limit`` messages (oldest first within the page).

    ``next_cursor`` loads earlier ones.
    """
    await session_for(services, user, session_id)
    async with services.db.sessions() as db:
        rows = (
            await db.scalars(
                select(Message)
                .where(
                    Message.session_id == session_id,
                    pagination.older_than(
                        Message.created_at, Message.id, cursor
                    ),
                )
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(limit + 1)
            )
        ).all()
    page = rows[:limit]
    more = len(rows) > limit
    return MessagePage(
        items=list(reversed(page)),
        next_cursor=pagination.encode(page[-1].created_at, page[-1].id)
        if more
        else None,
    )


@router.post(
    "/sessions/{session_id}/runs", response_model=RunStart, status_code=202
)
async def start_run(
    session_id: str,
    body: RunCreate,
    services: ServicesDep,
    user: UserDep,
    idempotency_key: Annotated[
        str | None, Header(max_length=128, alias="Idempotency-Key")
    ] = None,
):
    """Run the agent: a new turn (``input``) or an answer (``command``).

    With ``input`` while the session waits for an answer, the text answers
    the pending question (plan: revise feedback, approvals: reject with
    feedback, question: the answer).
    """
    await session_for(services, user, session_id, write=True)
    return await create_run(services, user, session_id, body, idempotency_key)


@router.get("/sessions/{session_id}/runs", response_model=RunPage)
async def list_runs(
    session_id: str,
    services: ServicesDep,
    user: UserDep,
    limit: int = pagination.Limit,
    cursor: str | None = None,
):
    await session_for(services, user, session_id)
    async with services.db.sessions() as db:
        rows = (
            await db.scalars(
                select(Run)
                .where(
                    Run.session_id == session_id,
                    pagination.older_than(Run.created_at, Run.id, cursor),
                )
                .order_by(Run.created_at.desc(), Run.id.desc())
                .limit(limit + 1)
            )
        ).all()
    page = rows[:limit]
    more = len(rows) > limit
    return RunPage(
        items=page,
        next_cursor=pagination.encode(page[-1].created_at, page[-1].id)
        if more
        else None,
    )


async def _run_for(
    services: Services, user: User, run_id: str, write: bool = False
) -> Run:
    async with services.db.sessions() as db:
        run = await db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "Run not found.")
    await session_for(services, user, run.session_id, write)
    return run


@router.get("/runs/{run_id}", response_model=RunRead)
async def get_run(run_id: str, services: ServicesDep, user: UserDep):
    return await _run_for(services, user, run_id)


@router.get("/runs/{run_id}/events", response_model=RunEvents)
async def run_events(
    run_id: str, services: ServicesDep, user: UserDep, types: str | None = None
):
    """Durable events of one turn, in order.

    Work steps, plan approvals, execution results, artifacts...
    The same events the SSE stream delivered live (token deltas and
    executor progress are live-only), so a client can redraw a past turn.
    ``types`` filters, e.g. ``execution_completed,artifact``.
    """
    run = await _run_for(services, user, run_id)
    async with services.db.sessions() as db:
        query = select(RunEvent).where(RunEvent.run_id == run_id)
        if types:
            query = query.where(
                RunEvent.type.in_(
                    [t.strip() for t in types.split(",") if t.strip()]
                )
            )
        rows = (
            await db.scalars(query.order_by(RunEvent.id).limit(5000))
        ).all()
    return RunEvents.model_validate(
        {"run_id": run_id, "status": run.status, "items": rows}
    )


@router.post("/runs/{run_id}/cancel", response_model=RunRead, status_code=202)
async def cancel_run(run_id: str, services: ServicesDep, user: UserDep):
    await _run_for(services, user, run_id, write=True)
    execution_id = None
    async with services.db.sessions() as db:
        run = await get_row(db, Run, run_id, lock=True)
        if run.status in {"succeeded", "failed", "cancelled"}:
            return run
        run.cancel_requested = True
        if run.status != "running":  # nobody is executing it: finish here
            execution_id = (run.waiting or {}).get("execution_id")
            run.status, run.waiting, run.finished_at = (
                "cancelled",
                None,
                utcnow(),
            )
            await db.execute(
                update(ChatSession)
                .where(
                    ChatSession.id == run.session_id,
                    ChatSession.active_run_id == run.id,
                )
                .values(active_run_id=None)
            )
        await db.commit()
    if run.status == "cancelled":
        await services.forget_tool_effects(run_id)
    if execution_id:
        try:
            await services.executor.cancel(
                execution_id,
                idempotency_key=f"cancel:{run_id}",
                reason="사용자 취소",
            )
        except ExecutorError:
            pass  # already terminal
    await services.events.emit(
        run.session_id, run.id, "run_status", {"status": run.status}
    )
    return run


@router.get("/sessions/{session_id}/events")
async def session_events(
    session_id: str,
    request: Request,
    services: ServicesDep,
    user: UserDep,
    after: int | None = None,
):
    """SSE.

    Resume with the ``Last-Event-ID`` header (or ``?after=``) after a
    reconnect.

    Without a cursor the stream replays the events of the session's active run.
    """
    session = await session_for(services, user, session_id)
    cursor = request.headers.get("last-event-id") or after

    async def history(after_id: int) -> list[dict]:
        if cursor:
            return await services.events.history(session_id, after_id)
        if not session.active_run_id:
            return []
        return await services.events.history(
            session_id, after_id, session.active_run_id
        )

    return event_stream(
        request,
        services.events,
        services.events.channel(session_id),
        history,
        cursor,
    )


@router.get("/sessions/{session_id}/outputs")
async def step_output_file(
    session_id: str,
    execution_id: str,
    path: str,
    services: ServicesDep,
    user: UserDep,
):
    """Images and files of executed steps.

    Paths come from execution_completed events.
    """
    await session_for(services, user, session_id)
    if not path.startswith(f"executions/{execution_id}/"):
        raise HTTPException(404, "Not found.")
    if not await execution_of_session(services, execution_id, session_id):
        raise HTTPException(404, "Not found.")
    file = services.storage.resolve_result(path)
    if not Path(file).is_file():
        raise HTTPException(404, "Not found.")
    return FileResponse(file)
