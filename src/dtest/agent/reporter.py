"""Report writer: turns executed code and its outputs into a Markdown report.

Used by the analyst (interactive sessions); the batch report agent
(agent.batch) starts from the same evidence. The model only sees bounded
evidence (call lines, observations, text output, errors); numbers must come
from that evidence.
"""

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from src.dtest.agent.codegen import (
    CUSTOM_SKILL,
    SETUP_TOOL,
    parse_observations,
)
from src.dtest.agent.llm import chat_model
from src.dtest.agent.prompts import load_prompt
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
            view = services.storage.read_step_outputs(
                step_result.get("result_ref"), max_chars=3000
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
                source = source_preview(services, step_result["result_ref"])
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


async def write_markdown(
    services: Services, model: str, system: str, request: str
) -> str:
    llm = chat_model(services.settings, model)
    response = await llm.ainvoke(
        [SystemMessage(system), HumanMessage(request)]
    )
    return response.text


async def generate_report(
    ctx, *, title: str, focus: str, evidence: str
) -> str:
    """Interactive report.

    ``ctx`` is the agent RunContext (project prompt + memory preferences).
    """
    services = ctx.services
    prompt = load_prompt("reporter")
    # the default Preferences topic, while the project keeps it
    preferences = next(
        (
            t["content"]
            for t in await services.memory.contents(ctx.project_id)
            if t["topic"] == "preferences"
        ),
        "",
    )
    system = prompt.render(
        project_prompt=ctx.project_prompt or "없음",
        report_preferences=preferences or "없음",
    )
    request = (
        f"# 제목\n{title}\n\n"
        f"# 사용자 요청\n{ctx.user_text}\n\n"
        f"# 강조할 점\n{focus}\n\n"
        f"# 근거\n{evidence}"
    )
    return await write_markdown(services, ctx.model, system, request)
