"""Server-sent events: stored events, then live ones from one channel."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from src.dtest.core.events import EVENTS_LOST, EventBus

HEARTBEAT = ": keep-alive\n\n"
History = Callable[[int], Awaitable[list[dict[str, Any]]]]


def event_stream(
    request: Request,
    events: EventBus,
    channel: str,
    history: History,
    cursor: int | str | None,
) -> StreamingResponse:
    """Replay ``history(after_id)``, then follow ``channel``.

    Listening starts before the replay so nothing falls in between;
    durable events already sent are skipped by id.
    """
    try:
        start = int(cursor) if cursor else 0
    except ValueError:
        raise HTTPException(422, "Last-Event-ID must be a number.") from None
    queue = events.listen_to(channel)

    async def stream():
        try:
            last = start
            for event in await history(last):
                last = event["id"]
                yield _format(event)
            while not await request.is_disconnected():
                try:
                    raw = await asyncio.wait_for(queue.get(), 15.0)
                except TimeoutError:
                    yield HEARTBEAT
                    continue
                if raw == EVENTS_LOST:
                    # live events were dropped: end here, the browser
                    # reconnects with Last-Event-ID and replays them
                    return
                event = json.loads(raw)
                if "id" in event:
                    if event["id"] <= last:
                        continue
                    last = event["id"]
                yield _format(event)
        except asyncio.CancelledError:
            pass
        finally:
            events.stop_listening(channel, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


def _format(event: dict[str, Any]) -> str:
    head = f"id: {event['id']}\n" if "id" in event else ""
    data = json.dumps(event, ensure_ascii=False, default=str)
    return f"{head}event: {event['type']}\ndata: {data}\n\n"
