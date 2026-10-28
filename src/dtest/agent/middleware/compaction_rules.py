"""What stays of an analysis once finish_analysis has closed it.

Kept: the task, the analyst's conclusions, report ids and the report's
summary/results, what ran and how it ended, skill/tool documents (latest
copy of each). Cleared: search results, raw observations; their
originals stay in the notebook, run events, executor and catalog.

Call arguments stay as written (the plan candidates included): the model
imitates its earlier calls, and compacted arguments became invalid calls.
"""

import json
from typing import Any

from src.dtest.agent.middleware.compaction import (
    Rule,
    ToolResultCompactionMiddleware,
)

PLACEHOLDER = "[정리됨] 끝난 분석의 {tool} 결과 (필요하면 다시 조회)"
SUPERSEDED = "[정리됨] 같은 {tool} 결과가 뒤에 다시 있음"
REPORT_SECTIONS = ("요약", "주요 결과")
REPORT_MAX = 1500
TABLES = ("DataFrame", "Series", "ndarray")


def execution_brief(content: str) -> str:
    """run_plan / run_custom_code result -> status, variables, errors."""
    try:
        body = json.loads(content)
    except ValueError:
        return content[:300]
    steps = body.get("results") or {"custom": body.get("result") or {}}
    lines = ["[정리됨] 실행 결과"]
    for label, view in steps.items():
        line = f"- {label}: {view.get('status')}"
        variables = [_variable(o) for o in view.get("observations") or []]
        if variables := [v for v in variables if v]:
            line += f" ({', '.join(variables)})"
        if error := view.get("error"):
            line += f" 오류: {str(error).splitlines()[0][:200]}"
        lines.append(line)
    if error := body.get("operation_error"):
        lines.append(f"실행 오류: {str(error)[:200]}")
    return "\n".join(lines)


def _variable(observation: Any) -> str:
    """``var(field=DataFrame [rows, cols], ...)`` for table-like outputs."""
    if not isinstance(observation, dict):
        return ""  # already cut down to a string by the tool
    value = observation.get("value")
    if not isinstance(value, dict):
        return str(observation.get("var") or "")
    fields = {"": value} if "type" in value else value
    parts = []
    for key, field in fields.items():
        if isinstance(field, dict) and field.get("type") in TABLES:
            shape = field.get("shape") or [field.get("len")]
            name = f"{key}=" if key else ""
            parts.append(f"{name}{field['type']} {shape}")
    var = observation.get("var") or ""
    return f"{var}({', '.join(parts)})" if parts else str(var)


def report_brief(content: str) -> str:
    """write_report result -> ids line + summary and results sections."""
    head, _, markdown = content.partition("\n\n")
    kept, keep = [], False
    for line in markdown.splitlines():
        if line.startswith("#"):
            keep = any(s in line for s in REPORT_SECTIONS)
            if not keep:
                continue
        if keep:
            kept.append(line)
    body = "\n".join(kept).strip()
    if len(body) > REPORT_MAX:
        body = body[:REPORT_MAX] + " ...(생략, 전체는 리포트 참고)"
    return f"{head}\n\n{body}" if body else head


RULES = {
    # documents the next analysis may plan from without reading them again
    "read_skill": Rule(latest_only=True),
    "read_tool": Rule(latest_only=True),
    "search_tools": Rule(result="clear"),
    "search_workflows": Rule(result="clear"),
    "run_plan": Rule(result=execution_brief),
    "run_custom_code": Rule(result=execution_brief),
    "write_report": Rule(result=report_brief),
}


def finished_analysis() -> ToolResultCompactionMiddleware:
    return ToolResultCompactionMiddleware(
        start_tools={"start_analysis"},
        end_tools={"finish_analysis"},
        rules=RULES,
        placeholder=PLACEHOLDER,
        truncated=" ...(생략)",
        superseded=SUPERSEDED,
    )
