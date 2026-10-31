"""Evidence of an execution, and the analysis report.

``collect_evidence`` is the bounded overview (call lines, observations,
text output, errors) both reports start from. The report agent
(agent.report_agent) reads the steps it needs in full with read_step;
numbers must come from that evidence. ``generate_report`` writes the
analysis report of a chat turn; agent.batch writes batch reports.
"""

import asyncio
import json
from typing import Any

from src.dtest.agent.codegen import (
    CUSTOM_SKILL,
    SETUP_TOOL,
    parse_observations,
)
from src.dtest.agent.context import ReportContext
from src.dtest.core.services import Services

EVIDENCE_MAX_CHARS = 40000


async def collect_evidence(
    services: Services, execution_id: str, plan: dict[str, Any] | None
) -> str:
    result = await services.executor.result(execution_id)
    parts: list[str] = []
    if plan and plan.get("document"):
        parts.append(
            "## 승인된 계획 (Workflow 1.0)\n"
            + json.dumps(plan["document"], ensure_ascii=False)
        )
        parts.append(
            "## 입력값\n"
            + json.dumps(plan["input_values"], ensure_ascii=False, default=str)
        )
    budget = EVIDENCE_MAX_CHARS - sum(map(len, parts))
    for operation in result.get("operations", []):
        for step in operation.get("steps", []):
            lineage = step.get("lineage") or {}
            if lineage.get("tool_name") == SETUP_TOOL:
                continue
            step_result = step.get("result") or {}
            view = await asyncio.to_thread(
                services.storage.read_step_outputs,
                step_result.get("result_ref"),
                max_chars=3000,
            )
            observations, text = parse_observations(view.get("text", ""))
            label = (
                f"{lineage.get('skill_name')}/{lineage.get('tool_name')}"
                if lineage.get("tool_name")
                else "code"
            )
            source = ""
            written = (
                not lineage.get("tool_name")
                or lineage.get("skill_name") == CUSTOM_SKILL
            )
            if written and view.get("available"):
                # code the agent or the batch author wrote: show it
                source = await asyncio.to_thread(
                    source_preview, services, step_result["result_ref"]
                )
            status = step_result.get("status")
            error = step_result.get("error_message")
            images = view.get("images")
            lines = [f"### Step {step['sequence']} {label} — {status}"]
            if lineage:
                inputs = _dumps(lineage.get("input_parameters", {}))
                lines.append(f"입력: {inputs}")
            if source:
                lines.append(f"코드:\n```python\n{source}\n```")
            if observations:
                lines.append(f"관측: {_dumps(observations)[:3000]}")
            if text.strip():
                lines.append(f"출력:\n{text[:2000]}")
            if images:
                lines.append(f"이미지 {len(images)}개 (내용은 볼 수 없음)")
            if error:
                lines.append(f"오류: {error}")
            block = "\n".join(filter(None, lines))
            if len(block) > budget:
                parts.append("(이후 Step은 분량 제한으로 생략)")
                return "\n\n".join(parts)
            parts.append(block)
            budget -= len(block)
    return "\n\n".join(parts)


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def source_preview(services: Services, result_ref: dict[str, Any]) -> str:
    """The step's code as the executor snapshotted it ("" if unreadable)."""
    return services.storage.step_source(result_ref)


_analysis_agents: dict[int, Any] = {}


def analysis_agent(settings):
    """The report agent with the analysis prompt, one per Settings."""
    from src.dtest.agent.report_agent import ReportAgent  # imports agent.tools

    key = id(settings)
    if key not in _analysis_agents:
        _analysis_agents[key] = ReportAgent(
            settings, "reporter", settings.report_model_call_limit
        )
    return _analysis_agents[key]


async def analysis_request(
    ctx, *, title: str, focus: str, evidence: str
) -> str:
    """What the report agent gets for an analysis report.

    ``ctx`` is the agent RunContext (project prompt + memory preferences).
    """
    # the default Preferences topic, while the project keeps it
    preferences = next(
        (
            t["content"]
            for t in await ctx.services.memory.contents(ctx.project_id)
            if t["topic"] == "preferences"
        ),
        "",
    )
    return (
        f"# 제목\n{title}\n\n"
        f"# 사용자 요청\n{ctx.user_text}\n\n"
        f"# 강조할 점\n{focus}\n\n"
        f"# 프로젝트 지침\n{ctx.project_prompt or '없음'}\n\n"
        "# 선호 (프로젝트 메모리 Preferences)\n"
        "보고서 형식·분석 방식에 관한 사용자 선호입니다. 보고서와 관계없는 "
        f"줄은 무시합니다.\n{preferences or '없음'}\n\n"
        f"# 실행 개요\n{evidence or '(Step 결과 없음)'}"
    )


async def generate_report(
    ctx, execution_id: str, *, title: str, focus: str, evidence: str
) -> str:
    """Interactive report (Markdown), written by the report agent.

    Its read_step calls show in the chat as progress; its text does not.
    """
    report_ctx = ReportContext(
        services=ctx.services,
        execution_id=execution_id,
        model=ctx.model,
        send=ctx.emit,
    )
    report = await analysis_agent(ctx.services.settings).write(
        report_ctx,
        await analysis_request(
            ctx, title=title, focus=focus, evidence=evidence
        ),
        title,
        quiet=("submit_report",),
    )
    return report["markdown"]
