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
``read_step``, all in one call. After writing, every number of the report
is looked up in the evidence it was given; numbers found nowhere get one
repair call. No checkpointer: a retry starts over.
"""

import logging
import re
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ToolErrorMiddleware,
)
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.dtest.agent.context import ReportState
from src.dtest.agent.llm import chat_model
from src.dtest.agent.middleware import (
    JsonArgumentsMiddleware,
    ToolFailureLimitMiddleware,
)
from src.dtest.agent.prompts import load_prompt
from src.dtest.agent.tools.batch import read_step, submit_report
from src.dtest.core.config import Settings

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
        self.tools = [read_step, submit_report] if submit else [read_step]
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
                tools=self.tools,
                system_prompt=load_prompt(self.prompt).render(),
                middleware=middleware,
                state_schema=ReportState,
            )
        return self._graphs[name]

    async def _run(
        self, ctx: Any, messages: list, quiet: tuple[str, ...]
    ) -> dict[str, Any]:
        from src.dtest.agent.graph import relay

        return await relay(
            self.get(ctx.model).astream(
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
        request: str,
        default_title: str,
        quiet: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """{title, markdown, summary}.

        ``ctx`` needs services, execution_id, model, cache and emit; tool
        calls not in ``quiet`` go out as tool_call events.
        """
        state = await self._run(ctx, [HumanMessage(request)], quiet)
        report = handed_in(state, default_title)
        missing = unsupported_numbers(report["markdown"], sources(state))
        if not missing:
            return report
        log.info(
            "report_numbers_unsupported execution=%s numbers=%s",
            ctx.execution_id,
            missing[:20],
        )
        fix = HumanMessage(repair_request(missing, self.submit))
        try:
            fixed_state = await self._run(
                ctx, [*state["messages"], fix], quiet
            )
            fixed = handed_in(fixed_state, default_title)
        except ReportMissing:
            return report
        if self.submit and not fixed_state.get("report"):
            return report  # answered instead of handing in a new report
        if len(fixed["markdown"]) < len(report["markdown"]) / 2:
            return report  # a reply about the report, not a report
        return fixed


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


def repair_request(missing: list[str], submit: bool) -> str:
    listed = ", ".join(missing[:30])
    how = (
        "고친 리포트 전체를 submit_report로 다시 제출하세요."
        if submit
        else "고친 리포트 전체를 다시 쓰세요(Markdown만, 설명 없이)."
    )
    return (
        "검토: 리포트의 다음 수치는 받은 근거(실행 개요, read_step 결과)에서 "
        f"찾지 못했습니다: {listed}\n"
        "근거의 값을 반올림하거나 백분율로 바꾼 것이면 그대로 두고, 근거에 "
        "없는 값이면 근거의 값으로 고치거나 지우세요. 필요하면 read_step으로 "
        f"확인하세요. {how}"
    )


def sources(state: dict[str, Any]) -> str:
    """What the agent was given: the request and the steps it read."""
    return "\n".join(
        m.text
        for m in state.get("messages", [])
        if isinstance(m, HumanMessage | ToolMessage)
    )


# dates, times and step/section references are not measured values
_SKIP = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?)?"
    r"|\d{1,2}:\d{2}(?::\d{2})?"
    r"|(?:Step|step|단계)\s*\d+"
)
_NUMBER = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?%?")


def _numbers(text: str) -> list[tuple[str, float, int, bool]]:
    """(as written, value, decimals, percent) of each number."""
    found = []
    for match in _NUMBER.finditer(_SKIP.sub(" ", text)):
        raw = match.group().rstrip(",")
        percent = raw.endswith("%")
        body = raw.rstrip("%").replace(",", "")
        try:
            value = float(body)
        except ValueError:
            continue
        mantissa = body.lower().split("e")[0]
        decimals = len(mantissa.split(".")[1]) if "." in mantissa else 0
        found.append((raw, value, decimals, percent))
    return found


def unsupported_numbers(markdown: str, evidence: str) -> list[str]:
    """Numbers of the report found nowhere in the evidence.

    A report number is supported when an evidence number equals it after
    rounding to the report's decimals, or after ×100 for a percentage.
    Whole numbers under 100 (counts, list numbers, quartile positions)
    are not checked.
    """
    known = [v for _, v, _, _ in _numbers(evidence)]
    known_set = set(known)
    missing: list[str] = []
    for raw, value, decimals, percent in _numbers(markdown):
        if decimals == 0 and abs(value) < 100 and not percent:
            continue
        if value in known_set:
            continue
        tolerance = 0.5 * 10**-decimals + 1e-12
        candidates = known + ([k * 100 for k in known] if percent else [])
        if any(abs(k - value) <= tolerance for k in candidates):
            continue
        if raw not in missing:
            missing.append(raw)
    return missing
