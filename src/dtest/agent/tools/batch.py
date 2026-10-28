"""Tools of the batch report agent (agent.batch).

The batch already ran on the executor; the agent only reads its results
and hands in the report. Nothing here sends code to the executor.
"""

import json
from typing import Any

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.dtest.agent.codegen import parse_observations
from src.dtest.agent.context import BatchReportContext, BatchReportState
from src.dtest.agent.reporter import source_preview

Runtime = ToolRuntime[BatchReportContext, BatchReportState]
STEP_MAX_CHARS = 12000
SUMMARY_MAX_CHARS = 2000


@tool
async def read_step(sequence: int, runtime: Runtime) -> str:
    """Everything one step of the batch run left: its code, text output
    (up to 12,000 chars), observations and error.

    Use it when the overview cut a step short or you need its exact
    numbers. sequence: the step number shown in the overview.
    """
    ctx = runtime.context
    services = ctx.services
    if "result" not in ctx.cache:
        ctx.cache["result"] = await services.executor.result(ctx.execution_id)
    step = next(
        (
            s
            for o in ctx.cache["result"].get("operations", [])
            for s in o.get("steps", [])
            if s.get("sequence") == sequence
        ),
        None,
    )
    if step is None:
        return f"Step {sequence}은 이 실행에 없습니다."
    step_result = step.get("result") or {}
    ref = step_result.get("result_ref")
    view = services.storage.read_step_outputs(ref, max_chars=STEP_MAX_CHARS)
    observations, text = parse_observations(view.get("text", ""))
    return json.dumps(
        {
            "sequence": sequence,
            "status": step_result.get("status"),
            "code": source_preview(services, ref) if ref else "",
            "observations": observations,
            "output": text,
            "truncated": view.get("truncated", False),
            "images": len(view.get("images") or []),
            "error": step_result.get("error_message") or view.get("error"),
        },
        ensure_ascii=False,
        default=str,
    )


@tool(return_direct=True)
async def submit_report(
    title: str, markdown: str, summary: str, runtime: Runtime
) -> Command:
    """Hand in the finished report. Call exactly once, at the end.

    title: one line naming the batch and what this run found.
    markdown: the full report (Korean Markdown).
    summary: what the next run of this batch should compare against: the
    key numbers and findings of this run, plain text, at most 2,000 chars.
    """
    report: dict[str, Any] = {
        "title": title.strip()[:200] or "배치 실행 리포트",
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
