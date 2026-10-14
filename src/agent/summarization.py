"""LangChain's SummarizationMiddleware, with progress for the client.

While the summary model runs the client gets an ``activity`` event
(summarizing); when it is done a durable ``context_summarized`` event marks
where the conversation was condensed, so a reloaded session can show it.
"""

from contextvars import ContextVar
from typing import Any

from langchain.agents.middleware import SummarizationMiddleware

from agent.context import RunContext

_context: ContextVar[RunContext | None] = ContextVar(
    "summarization_context", default=None
)


class ReportingSummarizationMiddleware(SummarizationMiddleware):
    async def abefore_model(self, state, runtime) -> dict[str, Any] | None:
        token = _context.set(getattr(runtime, "context", None))
        try:
            return await super().abefore_model(state, runtime)
        finally:
            _context.reset(token)

    # Called only when a summary is actually made. Private in LangChain;
    # tests/test_summarization.py fails if it goes away.
    async def _acreate_summary(self, messages_to_summarize) -> str:
        ctx = _context.get()
        if ctx is None:
            return await super()._acreate_summary(messages_to_summarize)
        count = len(messages_to_summarize)
        async with ctx.activity("summarizing", messages=count):
            summary = await super()._acreate_summary(messages_to_summarize)
        await ctx.emit(
            "context_summarized",
            {"messages": count, "summary_chars": len(summary)},
        )
        return summary
