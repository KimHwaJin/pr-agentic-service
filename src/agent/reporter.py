"""Evidence of an execution, and the analysis report.

``collect_evidence`` is the bounded overview (call lines, observations,
text output, errors) both reports start from. The report agent
(agent.report_agent) reads the steps it needs in full with read_step;
numbers must come from that evidence. ``generate_report`` writes the
analysis report of a chat turn; agent.batch writes batch reports.
"""

import asyncio
import json
import re
from typing import Any

from agent.codegen import CUSTOM_SKILL, SETUP_TOOL, parse_observations
from agent.context import ReportContext
from core import figures
from core.services import Services

# what one step shows in full: the read_step view
STEP_MAX_CHARS = 12000
# a trimmed step (the whole overview over budget) keeps this much
TRIM_OUTPUT_CHARS = 2000
TRIM_OBSERVATION_CHARS = 3000
# every note collect_evidence leaves on a trimmed or omitted step
_TRIMMED = re.compile(r"^※ .*read_step으로", re.M)


def trimmed(evidence: str) -> bool:
    """True when the evidence left part of a step out (read_step needed)."""
    return bool(_TRIMMED.search(evidence))


async def collect_evidence(
    services: Services,
    execution_id: str,
    plan: dict[str, Any] | None,
    max_chars: int | None = None,
) -> str:
    """Overview of every step for the report writer.

    Each step is shown whole (output up to STEP_MAX_CHARS, every
    observation) while the overview fits ``max_chars``
    (REPORT_EVIDENCE_MAX_CHARS). Over it, outputs and observations are
    trimmed and each trimmed step says so; steps past the budget are named
    as omitted. Only marked steps need read_step.
    """
    budget_total = max_chars or services.settings.report_evidence_max_chars
    result = await services.executor.result(execution_id)
    head: list[str] = []
    if plan and plan.get("document"):
        head.append(
            "## 승인된 계획 (Workflow 1.0)\n"
            + json.dumps(plan["document"], ensure_ascii=False)
        )
        head.append(
            "## 입력값\n"
            + json.dumps(plan["input_values"], ensure_ascii=False, default=str)
        )
    steps = _steps(result)
    views = [await step_view(services, s) for s in steps]
    full = [step_block(v, trim=False) for v in views]
    budget = budget_total - sum(map(len, head))
    if sum(map(len, full)) <= budget:
        return "\n\n".join(head + full)
    parts = list(head)
    for i, view in enumerate(views):
        block = step_block(view, trim=True)
        if len(block) > budget:
            rest = ", ".join(str(v["sequence"]) for v in views[i:])
            parts.append(
                f"※ Step {rest}: 분량 제한으로 생략. read_step으로 읽으세요."
            )
            break
        parts.append(block)
        budget -= len(block)
    return "\n\n".join(parts)


def _steps(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        s
        for o in result.get("operations", [])
        for s in o.get("steps", [])
        if (s.get("lineage") or {}).get("tool_name") != SETUP_TOOL
    ]


# what the report writer is told when it gets the steps' figures
FIGURES_NOTE = (
    "# 실행 결과 그림\n"
    "아래는 Step이 만든 그림(플롯) 일부입니다. 분포, 추세, 이상치 같은 "
    "경향을 설명하는 데에만 쓰고, 리포트의 수치는 위 실행 개요의 텍스트에서만 "
    "가져오세요. 그림을 언급할 때는 Step 번호로 가리키세요."
)


async def collect_figures(
    services: Services, execution_id: str, count: int
) -> list[dict[str, Any]]:
    """Content blocks of the steps' figures for a vision report writer.

    Empty when ``count`` is 0 (a text model, or figures turned off): then
    nothing is read and the request stays text.
    """
    if count <= 0:
        return []
    result = await services.executor.result(execution_id)
    steps = []
    for step in _steps(result):
        ref = (step.get("result") or {}).get("result_ref")
        view = await asyncio.to_thread(
            services.storage.read_step_outputs, ref, max_chars=0
        )
        if view.get("images"):
            lineage = step.get("lineage") or {}
            label = (
                f"{lineage.get('skill_name')}/{lineage.get('tool_name')}"
                if lineage.get("tool_name")
                else "code"
            )
            steps.append(
                (f"Step {step.get('sequence')} {label}", view["images"])
            )
    chosen = figures.pick(steps, count)
    loaded = await asyncio.to_thread(figures.load, services.storage, chosen)
    return figures.blocks(loaded)


def with_figures(request: str, blocks: list[dict[str, Any]]) -> Any:
    """The report request, with the figures after it when there are any."""
    if not blocks:
        return request
    return [
        {"type": "text", "text": request},
        {"type": "text", "text": FIGURES_NOTE},
        *blocks,
    ]


async def step_view(
    services: Services, step: dict[str, Any]
) -> dict[str, Any]:
    lineage = step.get("lineage") or {}
    step_result = step.get("result") or {}
    ref = step_result.get("result_ref")
    view = await asyncio.to_thread(
        services.storage.read_step_outputs, ref, max_chars=STEP_MAX_CHARS
    )
    observations, text = parse_observations(view.get("text", ""))
    written = (
        not lineage.get("tool_name")
        or lineage.get("skill_name") == CUSTOM_SKILL
    )
    source = ""
    if written and view.get("available"):
        # code the agent or the batch author wrote: show it
        source = await asyncio.to_thread(source_preview, services, ref)
    return {
        "sequence": step.get("sequence"),
        "label": (
            f"{lineage.get('skill_name')}/{lineage.get('tool_name')}"
            if lineage.get("tool_name")
            else "code"
        ),
        "status": step_result.get("status"),
        "inputs": lineage.get("input_parameters", {}) if lineage else None,
        "source": source,
        "observations": _dumps(observations) if observations else "",
        "text": text.strip(),
        # the output went past STEP_MAX_CHARS: even read_step shows a part
        "clipped": view.get("truncated", False),
        "images": len(view.get("images") or []),
        "error": step_result.get("error_message") or view.get("error"),
    }


def step_block(view: dict[str, Any], *, trim: bool) -> str:
    observations, text = view["observations"], view["text"]
    cut = []
    if trim and len(observations) > TRIM_OBSERVATION_CHARS:
        cut.append(f"관측 {TRIM_OBSERVATION_CHARS:,}/{len(observations):,}자")
        observations = observations[:TRIM_OBSERVATION_CHARS]
    if trim and len(text) > TRIM_OUTPUT_CHARS:
        cut.append(f"출력 {TRIM_OUTPUT_CHARS:,}/{len(text):,}자")
        text = text[:TRIM_OUTPUT_CHARS]
    lines = [f"### Step {view['sequence']} {view['label']} — {view['status']}"]
    if cut:
        lines.append(
            f"※ 일부만 표시({', '.join(cut)}). read_step으로 전체를 읽으세요."
        )
    if view["inputs"] is not None:
        lines.append(f"입력: {_dumps(view['inputs'])}")
    if view["source"]:
        lines.append(f"코드:\n```python\n{view['source']}\n```")
    if observations:
        lines.append(f"관측: {observations}")
    if text:
        lines.append(f"출력:\n{text}")
    if view["clipped"]:
        lines.append(f"(출력이 {STEP_MAX_CHARS:,}자를 넘어 이후는 볼 수 없음)")
    if view["images"]:
        lines.append(f"이미지 {view['images']}개 (내용은 볼 수 없음)")
    if view["error"]:
        lines.append(f"오류: {view['error']}")
    return "\n".join(lines)


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def source_preview(services: Services, result_ref: dict[str, Any]) -> str:
    """The step's code as the executor snapshotted it ("" if unreadable)."""
    return services.storage.step_source(result_ref)


_analysis_agents: dict[int, Any] = {}


def analysis_agent(settings):
    """The report agent with the analysis prompt, one per Settings."""
    from agent.report_agent import ReportAgent  # imports agent.tools

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

    Its read_step calls show in the chat as progress; its text (the
    report itself) does not, the report arrives as an artifact.
    """
    report_ctx = ReportContext(
        services=ctx.services,
        execution_id=execution_id,
        model=ctx.model,
        send=ctx.emit,
    )
    settings = ctx.services.settings
    request = await analysis_request(
        ctx, title=title, focus=focus, evidence=evidence
    )
    blocks = await collect_figures(
        ctx.services,
        execution_id,
        figures.limit(settings, ctx.model, settings.report_max_images),
    )
    report = await analysis_agent(settings).write(
        report_ctx,
        with_figures(request, blocks),
        title,
        can_read=trimmed(evidence),
    )
    return report["markdown"]
