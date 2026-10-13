"""Report writer: turns executed code and its outputs into a Markdown report.

Used by the analyst (interactive sessions) and by pr-batch report jobs. The
model only sees bounded evidence (call lines, observations, text output,
errors); numbers must come from that evidence.
"""

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent.codegen import SETUP_TOOL, parse_observations
from agent.llm import chat_model
from agent.prompts import load_prompt
from core.services import Services

EVIDENCE_MAX_CHARS = 40000


async def collect_evidence(
    services: Services, execution_id: str, plan: dict[str, Any] | None
) -> str:
    result = await services.executor.result(execution_id)
    parts: list[str] = []
    if plan:
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
            if not lineage.get("tool_name") and view.get("available"):
                source = _source_preview(services, step_result["result_ref"])
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


def _source_preview(services: Services, result_ref: dict[str, Any]) -> str:
    manifest = json.loads(
        services.storage.resolve_result(result_ref["relative_path"]).read_text(
            "utf-8"
        )
    )
    source = manifest.get("source") or {}
    if not source.get("relative_path"):
        return ""
    return services.storage.resolve_result(source["relative_path"]).read_text(
        "utf-8"
    )[:2000]


async def write_markdown(
    services: Services, model_alias: str, system: str, request: str
) -> str:
    model = chat_model(services.settings, model_alias)
    response = await model.ainvoke(
        [SystemMessage(system), HumanMessage(request)]
    )
    return (
        response.text if hasattr(response, "text") else str(response.content)
    )


async def generate_report(
    ctx, *, title: str, focus: str, evidence: str
) -> str:
    """Interactive report.

    ``ctx`` is the agent RunContext (project prompt + memory preferences).
    """
    services = ctx.services
    prompt = load_prompt(services.settings.prompts_root, "reporter")
    preferences = [
        m
        for m in await services.memory.entries(ctx.project_id)
        if m["category"] == "report_preferences"
    ]
    system = prompt.render(
        project_prompt=ctx.project_prompt or "없음",
        report_preferences="\n".join(
            f"- {m['title']}: {m['content']}" for m in preferences
        )
        or "없음",
    )
    request = (
        f"# 제목\n{title}\n\n"
        f"# 사용자 요청\n{ctx.user_text}\n\n"
        f"# 강조할 점\n{focus}\n\n"
        f"# 근거\n{evidence}"
    )
    return await write_markdown(services, ctx.model_alias, system, request)


async def generate_batch_report(
    services: Services, execution_id: str, options: dict[str, Any]
) -> str:
    """Report for a pr-batch script run.

    No conversation, no plan, no project context.
    """
    evidence = await collect_evidence(services, execution_id, plan=None)
    system = load_prompt(services.settings.prompts_root, "reporter").render(
        project_prompt="없음", report_preferences="없음"
    )
    title = options.get("title") or "배치 실행 리포트"
    request = (
        f"# 제목\n{title}\n\n"
        "# 사용자 요청\n배치 스크립트 실행 결과 정리\n\n"
        f"# 근거\n{evidence}"
    )
    return await write_markdown(
        services, services.settings.llm_default_alias, system, request
    )
