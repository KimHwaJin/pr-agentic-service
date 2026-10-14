import asyncio
from typing import Any, cast

import pytest
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphInterrupt

from agent.activity import LABELS, activity
from agent.middleware.summarization import ReportingSummarizationMiddleware


class _Events:
    def __init__(self):
        self.sent = []

    async def emit(self, type, data, durable=True):
        self.sent.append((type, data, durable))


def _run(body, kind="report_writing"):
    events = _Events()

    async def main():
        async with activity(events.emit, kind):
            await body()

    return events, main


def test_start_and_end_events_share_an_id():
    async def body():
        pass

    events, main = _run(body)
    asyncio.run(main())
    (t1, start, d1), (t2, end, d2) = events.sent
    assert t1 == t2 == "activity" and not d1 and not d2
    assert (
        start["state"] == "started"
        and start["label"] == LABELS["report_writing"]
    )
    assert end["id"] == start["id"] and end["state"] == "finished"
    assert end["elapsed_ms"] >= 0


@pytest.mark.parametrize(
    ("error", "state"),
    [(GraphInterrupt(()), "paused"), (RuntimeError("x"), "failed")],
)
def test_end_state_follows_how_the_block_ended(error, state):
    async def body():
        raise error

    events, main = _run(body)
    with pytest.raises(type(error)):
        asyncio.run(main())
    assert events.sent[-1][1]["state"] == state


def test_summary_reports_progress_and_marks_the_history(monkeypatch):
    from agent.middleware import summarization

    # the hook overridden here is private in LangChain
    assert hasattr(SummarizationMiddleware, "_acreate_summary")

    class Ctx(_Events):
        def activity(self, kind, label=None, **detail):
            return activity(self.emit, kind, label, **detail)

    async def base(self, messages_to_summarize):
        return "요약"

    monkeypatch.setattr(SummarizationMiddleware, "_acreate_summary", base)
    middleware = object.__new__(ReportingSummarizationMiddleware)
    ctx = Ctx()

    async def main():
        token = summarization._context.set(cast(Any, ctx))  # as abefore_model
        try:
            return await middleware._acreate_summary(
                [HumanMessage("a"), HumanMessage("b")]
            )
        finally:
            summarization._context.reset(token)

    assert asyncio.run(main()) == "요약"
    types = [(t, d.get("state")) for t, d, _ in ctx.sent]
    assert types == [
        ("activity", "started"),
        ("activity", "finished"),
        ("context_summarized", None),
    ]
    assert ctx.sent[-1][1] == {"messages": 2, "summary_chars": 2}
    assert ctx.sent[-1][2] is True  # durable: drawn again on reload
