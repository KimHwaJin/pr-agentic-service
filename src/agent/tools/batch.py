"""Tools of the report agent (agent.report_agent).

Used for analysis and batch reports. The execution already ran on the
executor; the agent only reads its results and hands in the report.
Nothing here sends code to the executor.
"""

from typing import Any

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from agent.context import ReportState
from agent.reporter import step_block, step_view

# context: agent.context.ReportContext (analysis) or BatchReportContext
Runtime = ToolRuntime[Any, ReportState]
SUMMARY_MAX_CHARS = 2000
STEPS_PER_READ = 6


@tool
async def read_step(sequences: list[int], runtime: Runtime) -> str:
    """Steps the overview marked as trimmed or omitted, shown whole: code,
    observations, text output (up to 12,000 chars each), error.

    Ask for every marked step you need in one call (up to 6). Steps the
    overview shows without a mark are already complete there.
    sequences: step numbers from the overview.
    """
    ctx = runtime.context
    if "result" not in ctx.cache:
        ctx.cache["result"] = await ctx.services.executor.result(
            ctx.execution_id
        )
    steps = {
        s.get("sequence"): s
        for o in ctx.cache["result"].get("operations", [])
        for s in o.get("steps", [])
    }
    blocks = []
    for sequence in list(dict.fromkeys(sequences))[:STEPS_PER_READ]:
        if sequence not in steps:
            blocks.append(f"### Step {sequence}\n이 실행에 없는 Step입니다.")
            continue
        view = await step_view(ctx.services, steps[sequence])
        blocks.append(step_block(view, trim=False))
    if len(sequences) > STEPS_PER_READ:
        blocks.append(f"(한 번에 {STEPS_PER_READ}개까지 읽습니다)")
    return "\n\n".join(blocks)


@tool(return_direct=True)
async def submit_report(
    title: str, markdown: str, summary: str, runtime: Runtime
) -> Command:
    """Hand in the finished report. Call exactly once, at the end.

    title: one line naming what was analysed and what it found.
    markdown: the full report (Korean Markdown).
    summary: the key numbers and findings, plain text, at most 2,000
    chars (a batch's next run compares against it).
    """
    report: dict[str, Any] = {
        "title": title.strip()[:200],  # empty: the caller's default
        "markdown": markdown,
        "summary": summary.strip()[:SUMMARY_MAX_CHARS],
    }
    return Command(
        update={
            "report": report,
            "messages": [
                ToolMessage(
                    "리포트를 받았습니다.", tool_call_id=runtime.tool_call_id
                )
            ],
        }
    )
