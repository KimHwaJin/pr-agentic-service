"""Report agent: reads a finished execution and writes its report.

One agent writes both reports, each with its own prompt:

- analysis report (``write_report`` in a chat turn): prompt ``reporter``,
  ``REPORT_MODEL_CALL_LIMIT`` model calls; the report is its final answer
  (see agent.reporter)
- batch report (the report worker): prompt ``batch_analyst``,
  ``BATCH_REPORT_MODEL_CALL_LIMIT`` model calls; the report comes through
  ``submit_report`` with a summary for the next run (see agent.batch)

The evidence (agent.reporter.collect_evidence) holds every step whole while
it fits REPORT_EVIDENCE_MAX_CHARS, so most reports take one model call.
Over it, trimmed steps are marked and the agent reads them with
``read_step``, all in one call. No checkpointer: a retry starts over.
"""

import logging
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ToolErrorMiddleware,
)
from langchain_core.messages import AIMessage, HumanMessage

from agent.context import ReportState
from agent.llm import chat_model
from agent.middleware import (
    JsonArgumentsMiddleware,
    ToolFailureLimitMiddleware,
)
from agent.prompts import load_prompt
from agent.tools.batch import read_step, submit_report
from core.config import Settings

log = logging.getLogger(__name__)


class ReportMissing(RuntimeError):
    """The agent ended without a report."""


class ReportAgent:
    """One compiled graph per served model name.

    ``submit``: the report comes through submit_report (batch: it carries
    the summary); otherwise it is the agent's final answer.
    """

    def __init__(
        self,
        settings: Settings,
        prompt: str,
        call_limit: int,
        submit: bool = False,
    ):
        self.settings, self.prompt, self.call_limit, self.submit = (
            settings,
            prompt,
            call_limit,
            submit,
        )
        self._graphs: dict[tuple[str, bool], Any] = {}

    def tools(self, can_read: bool) -> list:
        """read_step only when the evidence left something out."""
        return [read_step] * can_read + [submit_report] * self.submit

    def get(self, name: str, can_read: bool = True):
        key = (name, can_read)
        if key not in self._graphs:
            # agent.graph imports the tools
            from agent.graph import tool_error

            middleware: list[AgentMiddleware[Any, Any, Any]] = [
                JsonArgumentsMiddleware(),
                ToolFailureLimitMiddleware(
                    self.settings.agent_tool_failure_limit
                ),
                ToolErrorMiddleware(on_error=tool_error),
                ModelCallLimitMiddleware(
                    run_limit=self.call_limit, exit_behavior="end"
                ),
            ]
            self._graphs[key] = create_agent(
                chat_model(self.settings, name),
                tools=self.tools(can_read),
                system_prompt=load_prompt(self.prompt).render(),
                middleware=middleware,
                state_schema=ReportState,
            )
        return self._graphs[key]

    async def _run(
        self,
        ctx: Any,
        messages: list,
        quiet: tuple[str, ...],
        can_read: bool,
    ) -> dict[str, Any]:
        from agent.graph import relay

        return await relay(
            self.get(ctx.model, can_read).astream(
                {"messages": messages},
                {"recursion_limit": self.settings.agent_recursion_limit},
                context=ctx,
                stream_mode=["messages", "updates", "values"],
            ),
            ctx.emit,
            quiet=quiet,
        )

    async def write(
        self,
        ctx: Any,
        request: str | list[dict[str, Any]],
        default_title: str,
        quiet: tuple[str, ...] = (),
        can_read: bool = True,
    ) -> dict[str, Any]:
        """{title, markdown, summary}.

        ``ctx`` needs services, execution_id, model, cache and emit; tool
        calls not in ``quiet`` go out as tool_call events. ``can_read``
        False (the request already holds every step in full) binds no
        read_step, so an analysis report is one model call. ``request``
        is text, or content blocks (text and the steps' figures) for a
        vision model.
        """
        state = await self._run(ctx, [HumanMessage(request)], quiet, can_read)
        return handed_in(state, default_title)


def handed_in(state: dict[str, Any], default_title: str) -> dict[str, Any]:
    """The submitted report; else the agent's last text as the report."""
    if report := state.get("report"):
        return {**report, "title": report.get("title") or default_title}
    answers = [
        m
        for m in state.get("messages", [])
        if isinstance(m, AIMessage) and m.text.strip()
    ]
    # the final answer, not a line said before a tool call
    last = next(
        (m for m in reversed(answers) if not m.tool_calls),
        answers[-1] if answers else None,
    )
    if last is None:
        raise ReportMissing("the agent ended without a report")
    return {
        "title": default_title,
        "markdown": last.text,
        "summary": last.text[:2000],
    }
