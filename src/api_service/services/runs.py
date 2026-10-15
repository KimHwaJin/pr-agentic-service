"""Starting and resuming turns (``POST /sessions/{id}/runs``).

One run per session at a time: the session row lock serialises concurrent
requests. A new turn and an answer both end the same way: the run is
``queued`` and the workers are woken (after the commit, so a woken worker
always finds the row).
"""

import hashlib
import json

from api_service.errors import ApiError
from api_service.schemas import (
    Resume,
    RunCreate,
    RunInput,
    RunRead,
    RunStart,
    TextBlock,
)
from api_service.services import answers
from core import images as image_store
from core.db import get_row
from core.models import ChatSession, Image, Message, Run, RunRequest, User
from core.services import Services


async def create_run(
    services: Services,
    user: User,
    session_id: str,
    body: RunCreate,
    idempotency_key: str | None = None,
) -> RunStart:
    """Start a turn (``input``) or resume the waiting one (``command``).

    One run per session at a time: the session row lock serialises
    concurrent requests. Typed text while a question is pending answers it.
    """
    settings = services.settings
    spec = None
    if body.input is not None:
        spec = settings.model(body.model)
        if spec is None:
            raise ApiError(
                422,
                "unknown_model",
                "Unknown model.",
                models=[m.name for m in settings.models],
            )
        _check_images(services, body.input, spec)
    request_hash = _request_hash(body)
    images: list[Image] = []
    async with services.db.sessions() as db:
        session = await get_row(db, ChatSession, session_id, lock=True)
        if idempotency_key:
            seen = await db.get(RunRequest, (session_id, idempotency_key))
            if seen is not None:
                if seen.request_hash != request_hash:
                    raise ApiError(
                        409,
                        "idempotency_conflict",
                        "This Idempotency-Key was used for another request.",
                    )
                run = await get_row(db, Run, seen.run_id)
                return RunStart(
                    run=RunRead.model_validate(run), resumed=seen.resumed
                )
        active = (
            await db.get(Run, session.active_run_id)
            if session.active_run_id
            else None
        )
        try:
            if body.command is not None:
                run = _resume(active, body.command.resume)
                resumed, text, value = True, None, body.command.resume.value
            elif active is not None and active.status == "waiting_input":
                # typed while a question is pending: that is the answer
                assert body.input is not None
                waiting = active.waiting or {}
                text = body.input.text
                value = answers.from_text(waiting, text)
                run, resumed = active, True
            elif active is not None:
                raise ApiError(
                    409,
                    "session_busy",
                    "This session is still working. "
                    "Wait for it to finish or cancel it.",
                    run=RunRead.model_validate(active),
                )
            else:
                assert body.input is not None and spec is not None
                run = Run(
                    session_id=session.id,
                    project_id=session.project_id,
                    user_id=user.id,
                    status="queued",
                    model=spec.name,
                    input={},
                )
                db.add(run)
                await db.flush()
                images = await _save_images(services, user, session, run, body)
                run.input = _turn_input(body.input, images)
                resumed, text, value = False, body.input.text, None
                session.active_run_id = run.id
            if resumed:
                run.resume = {
                    "interrupt_id": (run.waiting or {}).get("interrupt_id"),
                    "value": value,
                }
                run.status, run.waiting = "queued", None
            if text is not None:
                db.add(
                    Message(
                        session_id=session.id,
                        run_id=run.id,
                        role="user",
                        content=text,
                        attachments=[_attachment(i) for i in images],
                    )
                )
            if idempotency_key:
                db.add(
                    RunRequest(
                        session_id=session_id,
                        key=idempotency_key,
                        request_hash=request_hash,
                        run_id=run.id,
                        resumed=resumed,
                    )
                )
            await db.commit()
        except BaseException:
            await services.images.remove([i.id for i in images])
            raise
    if resumed:
        await services.events.emit(
            session_id,
            run.id,
            "hitl_resolved",
            {"interrupt_id": (run.resume or {}).get("interrupt_id")},
        )
    else:
        await services.events.emit(
            session_id, run.id, "run_status", {"status": "queued"}
        )
    await services.events.wake_runs(run.id)
    return RunStart(run=RunRead.model_validate(run), resumed=resumed)


def _resume(active: Run | None, resume: Resume) -> Run:
    if active is None or active.status != "waiting_input":
        raise ApiError(
            409,
            "not_waiting",
            "No turn of this session is waiting for an answer.",
            run=RunRead.model_validate(active) if active else None,
        )
    waiting = active.waiting or {}
    if waiting.get("interrupt_id") != resume.interrupt_id:
        raise ApiError(
            409,
            "stale_interrupt",
            "The turn is waiting for a different question.",
            run=RunRead.model_validate(active),
        )
    errors = answers.validate(waiting, resume.value)
    if errors:
        raise ApiError(
            422, "invalid_answer", "The answer is not valid.", errors=errors
        )
    return active


def _check_images(services: Services, data: RunInput, spec) -> None:
    images = data.images
    if not images:
        return
    settings = services.settings
    if not spec.vision:
        raise ApiError(
            422,
            "model_not_multimodal",
            f"{spec.name} does not accept images.",
            models=[m.name for m in settings.models if m.vision],
        )
    if len(images) > spec.max_images:
        raise ApiError(
            422,
            "invalid_image",
            f"At most {spec.max_images} images per turn.",
            errors=[{"field": "input.content", "message": "too many images"}],
        )
    total = sum(len(i.base64) * 3 // 4 for i in images)
    if total > settings.image_max_total_bytes:
        raise ApiError(
            413,
            "image_too_large",
            "Images are too large in total.",
            max_bytes=settings.image_max_total_bytes,
        )


async def _save_images(
    services: Services,
    user: User,
    session: ChatSession,
    run: Run,
    body: RunCreate,
) -> list[Image]:
    assert body.input is not None
    saved: list[Image] = []
    try:
        for n, block in enumerate(body.input.images):
            try:
                prepared = image_store.prepare(
                    block.base64,
                    block.mime_type,
                    services.settings.image_max_bytes,
                )
            except image_store.ImageError as exc:
                raise ApiError(
                    422,
                    "invalid_image",
                    "An image could not be read.",
                    errors=[
                        {"field": f"input.images.{n}", "message": str(exc)}
                    ],
                ) from None
            saved.append(
                await services.images.save(
                    prepared,
                    user_id=user.id,
                    employee_id=user.employee_id,
                    project_id=session.project_id,
                    session_id=session.id,
                    run_id=run.id,
                    name=block.name,
                )
            )
    except BaseException:
        await services.images.remove([i.id for i in saved])
        raise
    return saved


def _turn_input(data: RunInput, images: list[Image]) -> dict:
    """run.input: the text, and content blocks with image references."""
    if not images:
        return {"text": data.text}
    by_order = iter(images)
    content = []
    for block in data.content:
        if isinstance(block, TextBlock):
            content.append({"type": "text", "text": block.text})
        else:
            image = next(by_order)
            content.append(
                {
                    "type": "image",
                    "file_id": image.id,
                    "mime_type": image.mime_type,
                    "extras": {"name": image.name},
                }
            )
    return {"text": data.text, "content": content}


def _attachment(image: Image) -> dict:
    return {
        "kind": "image",
        "image_id": image.id,
        "name": image.name,
        "mime_type": image.mime_type,
        "width": image.width,
        "height": image.height,
    }


def _request_hash(body: RunCreate) -> str:
    raw = json.dumps(body.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()
