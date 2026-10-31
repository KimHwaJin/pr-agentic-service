"""Dropped live events end the SSE stream so the browser replays them."""

import asyncio

from src.dtest.core.events import EVENTS_LOST, _mark_lost


def test_a_full_queue_is_cleared_and_marked():
    queue: asyncio.Queue = asyncio.Queue(2)
    queue.put_nowait("a")
    queue.put_nowait("b")
    _mark_lost(queue)
    items = [queue.get_nowait() for _ in range(queue.qsize())]
    assert items[-1] == EVENTS_LOST


def test_the_stream_ends_when_events_were_lost():
    import json
    from types import SimpleNamespace

    from src.dtest.api_service.sse import event_stream

    queue: asyncio.Queue = asyncio.Queue()
    queue.put_nowait(json.dumps({"id": 2, "type": "x", "data": {}}))
    queue.put_nowait(EVENTS_LOST)
    queue.put_nowait(json.dumps({"id": 3, "type": "x", "data": {}}))
    events = SimpleNamespace(
        listen_to=lambda channel: queue,
        stop_listening=lambda channel, q: None,
    )

    async def history(after):
        return [{"id": 1, "type": "x", "data": {}}]

    async def disconnected():
        return False

    request = SimpleNamespace(is_disconnected=disconnected)

    async def read():
        response = event_stream(request, events, "c", history, None)
        return [chunk async for chunk in response.body_iterator]

    chunks = asyncio.run(read())
    text = "".join(c if isinstance(c, str) else c.decode() for c in chunks)
    assert "id: 1" in text and "id: 2" in text and "id: 3" not in text
