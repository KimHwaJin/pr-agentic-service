"""Report agent: reads a finished execution and hands in its report.

One agent writes both reports, each with its own prompt:

- analysis report (``write_report`` in a chat turn): prompt ``reporter``,
  ``REPORT_MODEL_CALL_LIMIT`` model calls, see agent.reporter
- batch report (the report worker): prompt ``batch_analyst``,
  ``BATCH_REPORT_MODEL_CALL_LIMIT`` model calls, see agent.batch

It starts from the bounded overview of agent.reporter.collect_evidence,
reads the steps it needs in full with ``read_step`` and ends with
``submit_report``. No checkpointer: a retry starts over.
"""

from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ToolErrorMiddleware,
)
from langchain_core.messages import AIMessage, HumanMessage

from src.dtest.agent.context import ReportState
from src.dtest.agent.llm import chat_model
from src.dtest.agent.middleware import (
    JsonArgumentsMiddleware,
    ToolFailureLimitMiddleware,
)
from src.dtest.agent.prompts import load_prompt
from src.dtest.agent.tools.batch import read_step, submit_report
from src.dtest.core.config import Settings

TOOLS = [read_step, submit_report]


class ReportMissing(RuntimeError):
    """The agent ended without a report."""


class ReportAgent:
    """One compiled graph per served model name."""

    def __init__(self, settings: Settings, prompt: str, call_limit: int):
        self.settings, self.prompt, self.call_limit = (
            settings,
            prompt,
            call_limit,
        )
        self._graphs: dict[str, Any] = {}

    def get(self, name: str):
        if name not in self._graphs:
            # agent.graph imports the tools
            from src.dtest.agent.graph import tool_error

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
            self._graphs[name] = create_agent(
                chat_model(self.settings, name),
                tools=TOOLS,
                system_prompt=load_prompt(self.prompt).render(),
                middleware=middleware,
                state_schema=ReportState,
            )
        return self._graphs[name]

    async def write(
        self,
        ctx: Any,
        request: str,
        default_title: str,
        quiet: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """{title, markdown, summary}.

        ``ctx`` needs services, execution_id, model, cache and emit; tool
        calls not in ``quiet`` go out as tool_call events.
        """
        from src.dtest.agent.graph import relay

        state = await relay(
            self.get(ctx.model).astream(
                {"messages": [HumanMessage(request)]},
                {"recursion_limit": self.settings.agent_recursion_limit},
                context=ctx,
                stream_mode=["messages", "updates", "values"],
            ),
            ctx.emit,
            quiet=quiet,
        )
        return handed_in(state, default_title)


def handed_in(state: dict[str, Any], default_title: str) -> dict[str, Any]:
    """The submitted report; else the agent's last text as the report."""
    if report := state.get("report"):
        return {**report, "title": report.get("title") or default_title}
    last = next(
        (
            m
            for m in reversed(state.get("messages", []))
            if isinstance(m, AIMessage) and m.text.strip()
        ),
        None,
    )
    if last is None:
        raise ReportMissing("the agent ended without submitting a report")
    return {
        "title": default_title,
        "markdown": last.text,
        "summary": last.text[:2000],
    }
