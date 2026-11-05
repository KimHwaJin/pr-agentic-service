"""LangChain's SummarizationMiddleware, with progress for the client.

While the summary model runs the client gets an ``activity`` event
(summarizing); when it is done a durable ``context_summarized`` event marks
where the conversation was condensed, so a reloaded session can show it.
"""

from contextvars import ContextVar
from functools import partial
from typing import Any

from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages.utils import count_tokens_approximately

from agent.context import RunContext
from core.config import Settings

_context: ContextVar[RunContext | None] = ContextVar(
    "summarization_context", default=None
)


def summary_token_counter(settings: Settings, model: str):
    """The size estimate that decides when to summarize.

    LangChain counts an image as 85 tokens; a vision model really gets each
    of the recent turns' images (~1-1.5k tokens at 1568 px), so for it an
    image counts IMAGE_TOKENS. A text model gets a short placeholder
    instead, so its estimate stays LangChain's.
    """
    spec = settings.model(model)
    if spec is None or not spec.vision:
        return count_tokens_approximately
    return partial(
        count_tokens_approximately,
        tokens_per_image=settings.image_tokens,
        use_usage_metadata_scaling=True,
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
