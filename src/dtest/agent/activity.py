"""What the agent is busy with, for slow work the client cannot see.

Model calls that end in a tool call stream no text, and some steps
(summarizing the conversation, writing a report) take tens of seconds.
Wrap such work in ``ctx.activity(kind)``: the client gets a live-only
``activity`` event when it starts and another when it ends, and shows the
label of the one still running.

    async with ctx.activity("report_writing"):
        markdown = await generate_report(...)

New slow work only needs a kind and a label here. Executor runs are
covered by ``run_status`` (waiting_executor) and ``execution_progress``.
"""

import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from langgraph.errors import GraphInterrupt

LABELS = {
    "answering": "답변을 준비하는 중",  # main agent model call
    "planning": "분석 단계를 정하는 중",  # analyst model call
    "summarizing": "이전 대화를 정리하는 중",
    "report_writing": "리포트를 작성하는 중",
    "workflow_saving": "워크플로우를 저장하는 중",
}

Emit = Callable[..., Awaitable[None]]


@asynccontextmanager
async def activity(
    emit: Emit, kind: str, label: str | None = None, **detail: Any
) -> AsyncGenerator[None]:
    """Sends ``activity`` started/finished events around the block.

    state on the end event: finished | failed | paused (an interrupt).
    """
    activity_id = uuid.uuid4().hex
    started = time.monotonic()
    await emit(
        "activity",
        {
            "id": activity_id,
            "kind": kind,
            "state": "started",
            "label": label or LABELS.get(kind, kind),
            **detail,
        },
        durable=False,
    )
    state = "finished"
    try:
        yield
    except GraphInterrupt:
        state = "paused"
        raise
    except BaseException:
        state = "failed"
        raise
    finally:
        await emit(
            "activity",
            {
                "id": activity_id,
                "kind": kind,
                "state": state,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            },
            durable=False,
        )
