import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select, update

from api_service.deps import ServicesDep, UserDep, project_for, session_for
from api_service.schemas import (
    MessageCreate,
    MessageRead,
    ResumeRequest,
    RunRead,
    SessionCreate,
    SessionRead,
    SessionStart,
    SessionUpdate,
)
from core.db import utcnow
from core.executor.client import ExecutorError
from core.models import ChatSession, Message, Run, User
from core.services import Services

router = APIRouter(tags=["sessions"])
HEARTBEAT = ": keep-alive\n\n"
RESUME_TYPES = {"plan_approval", "code_approval", "memory_change", "workflow_save"}  # need a dict answer


async def start_run(services: Services, user: User, session_id: str, text: str, model_alias: str | None) -> Run:
    """One run per session at a time: the session row lock serialises concurrent sends."""
    alias = model_alias or services.settings.llm_default_alias
    if alias not in services.settings.llm_models:
        raise HTTPException(422, f"Unknown model alias. Choose one of {list(services.settings.llm_models)}.")
    async with services.db.sessions() as db:
        session = await db.get(ChatSession, session_id, with_for_update=True)
        if session.active_run_id:
            raise HTTPException(409, "This session is still working. Wait for it to finish or cancel it.")
        run = Run(
            session_id=session.id,
            project_id=session.project_id,
            user_id=user.id,
            status="queued",
            model_alias=alias,
            input={"text": text},
        )
        db.add(run)
        await db.flush()
        db.add(Message(session_id=session.id, run_id=run.id, role="user", content=text))
        session.active_run_id = run.id
        await db.commit()
    await services.events.emit(session_id, run.id, "run_status", {"status": "queued"})
    await services.events.wake_runs(run.id)
    return run


@router.post("/projects/{project_id}/sessions", response_model=SessionStart, status_code=201)
async def create_session(project_id: str, body: SessionCreate, services: ServicesDep, user: UserDep):
    """Creates a session; with ``message`` the first turn starts immediately (login -> chat)."""
    await project_for(services, user, project_id, write=True)
    title = body.title or (body.message[:40] if body.message else "새 대화")
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
    run = await start_run(services, user, session.id, body.message, body.model_alias) if body.message else None
    async with services.db.sessions() as db:
        session = await db.get(ChatSession, session.id)
    return SessionStart(session=SessionRead.model_validate(session), run=RunRead.model_validate(run) if run else None)


@router.get("/projects/{project_id}/sessions", response_model=list[SessionRead])
async def list_sessions(project_id: str, services: ServicesDep, user: UserDep):
    await project_for(services, user, project_id)
    async with services.db.sessions() as db:
        rows = await db.scalars(
            select(ChatSession)
            .where(ChatSession.project_id == project_id, ChatSession.deleted_at.is_(None))
            .order_by(ChatSession.updated_at.desc())
        )
        return rows.all()


@router.get("/sessions/{session_id}", response_model=SessionRead)
async def get_session(session_id: str, services: ServicesDep, user: UserDep):
    return await session_for(services, user, session_id)


@router.patch("/sessions/{session_id}", response_model=SessionRead)
async def update_session(session_id: str, body: SessionUpdate, services: ServicesDep, user: UserDep):
    await session_for(services, user, session_id, write=True)
    async with services.db.sessions() as db:
        session = await db.get(ChatSession, session_id)
        for key, value in body.model_dump(exclude_unset=True).items():
            setattr(session, key, value)
        if body.title is not None:
            session.title_source = "user"  # never auto-renamed again
        await db.commit()
        return session


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, services: ServicesDep, user: UserDep):
    session = await session_for(services, user, session_id, write=True)
    if session.active_run_id:
        raise HTTPException(409, "Cancel the running turn first.")
    async with services.db.sessions() as db:
        await db.execute(update(ChatSession).where(ChatSession.id == session_id).values(deleted_at=utcnow()))
        await db.commit()
    return Response(status_code=204)


@router.get("/sessions/{session_id}/messages", response_model=list[MessageRead])
async def list_messages(session_id: str, services: ServicesDep, user: UserDep):
    await session_for(services, user, session_id)
    async with services.db.sessions() as db:
        rows = await db.scalars(select(Message).where(Message.session_id == session_id).order_by(Message.created_at))
        return rows.all()


@router.post("/sessions/{session_id}/messages", response_model=RunRead, status_code=202)
async def send_message(session_id: str, body: MessageCreate, services: ServicesDep, user: UserDep):
    await session_for(services, user, session_id, write=True)
    return await start_run(services, user, session_id, body.content, body.model_alias)


@router.get("/sessions/{session_id}/runs", response_model=list[RunRead])
async def list_runs(session_id: str, services: ServicesDep, user: UserDep):
    await session_for(services, user, session_id)
    async with services.db.sessions() as db:
        rows = await db.scalars(
            select(Run).where(Run.session_id == session_id).order_by(Run.created_at.desc()).limit(100)
        )
        return rows.all()


async def _run_for(services: Services, user: User, run_id: str, write: bool = False) -> Run:
    async with services.db.sessions() as db:
        run = await db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "Run not found.")
    await session_for(services, user, run.session_id, write)
    return run


@router.get("/runs/{run_id}", response_model=RunRead)
async def get_run(run_id: str, services: ServicesDep, user: UserDep):
    return await _run_for(services, user, run_id)


@router.post("/runs/{run_id}/resume", response_model=RunRead, status_code=202)
async def resume_run(run_id: str, body: ResumeRequest, services: ServicesDep, user: UserDep):
    """Answer the run's pending question / approval (HITL)."""
    await _run_for(services, user, run_id, write=True)
    async with services.db.sessions() as db:
        run = await db.get(Run, run_id, with_for_update=True)
        if run.status != "waiting_input" or (run.waiting or {}).get("interrupt_id") != body.interrupt_id:
            raise HTTPException(409, "The run is not waiting for this answer.")
        if run.waiting.get("type") in RESUME_TYPES and not isinstance(body.value, dict):
            raise HTTPException(422, f"'{run.waiting['type']}' expects an object answer.")
        run.resume = {"interrupt_id": body.interrupt_id, "value": body.value}
        run.status, run.waiting = "queued", None
        await db.commit()
    await services.events.emit(run.session_id, run.id, "hitl_resolved", {"interrupt_id": body.interrupt_id})
    await services.events.wake_runs(run.id)
    return run


@router.post("/runs/{run_id}/cancel", response_model=RunRead, status_code=202)
async def cancel_run(run_id: str, services: ServicesDep, user: UserDep):
    await _run_for(services, user, run_id, write=True)
    execution_id = None
    async with services.db.sessions() as db:
        run = await db.get(Run, run_id, with_for_update=True)
        if run.status in {"succeeded", "failed", "cancelled"}:
            return run
        run.cancel_requested = True
        if run.status != "running":  # nobody is executing it: finish here
            execution_id = (run.waiting or {}).get("execution_id")
            run.status, run.waiting, run.finished_at = "cancelled", None, utcnow()
            await db.execute(
                update(ChatSession)
                .where(ChatSession.id == run.session_id, ChatSession.active_run_id == run.id)
                .values(active_run_id=None)
            )
        await db.commit()
    if execution_id:
        try:
            await services.executor.cancel(execution_id, idempotency_key=f"cancel:{run_id}", reason="사용자 취소")
        except ExecutorError:
            pass  # already terminal
    await services.events.emit(run.session_id, run.id, "run_status", {"status": run.status})
    return run


@router.get("/sessions/{session_id}/events")
async def session_events(
    session_id: str, request: Request, services: ServicesDep, user: UserDep, after: int | None = None
):
    """SSE. Resume with the ``Last-Event-ID`` header (or ``?after=``) after a reconnect.

    Without a cursor the stream replays the events of the session's active run.
    """
    session = await session_for(services, user, session_id)
    cursor = request.headers.get("last-event-id") or after
    queue = services.events.subscribe(session_id)

    async def stream():
        try:
            last = int(cursor) if cursor else 0
            history = await services.events.history(session_id, last, None if cursor else session.active_run_id)
            if not cursor and not session.active_run_id:
                history = []
            for event in history:
                last = event["id"]
                yield _sse(event)
            while not await request.is_disconnected():
                try:
                    raw = await asyncio.wait_for(queue.get(), 15.0)
                except TimeoutError:
                    yield HEARTBEAT
                    continue
                event = json.loads(raw)
                if "id" in event:
                    if event["id"] <= last:
                        continue
                    last = event["id"]
                yield _sse(event)
        except asyncio.CancelledError:
            pass
        finally:
            services.events.unsubscribe(session_id, queue)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    )


def _sse(event: dict) -> str:
    head = f"id: {event['id']}\n" if "id" in event else ""
    return f"{head}event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


@router.get("/sessions/{session_id}/outputs")
async def step_output_file(session_id: str, execution_id: str, path: str, services: ServicesDep, user: UserDep):
    """Images and files of executed steps (paths from execution_completed events)."""
    await session_for(services, user, session_id)
    if not path.startswith(f"executions/{execution_id}/"):
        raise HTTPException(404, "Not found.")
    try:
        execution = await services.executor.get(execution_id)
    except ExecutorError:
        raise HTTPException(404, "Not found.") from None
    if execution["context"].get("session_id") != session_id:
        raise HTTPException(404, "Not found.")
    file = services.storage.resolve_result(path)
    if not Path(file).is_file():
        raise HTTPException(404, "Not found.")
    return FileResponse(file)
