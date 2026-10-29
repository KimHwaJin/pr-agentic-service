"""Tools of the main (conversation) agent.

Domain knowledge, project memory, hand-off to analysis.
"""

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from agent.context import AnalysisState, RunContext
from core.memory.service import (
    SECTIONS,
    Actor,
    MemoryEditError,
    Section,
    updated_event,
)


@tool
async def read_knowledge(
    name: str, runtime: ToolRuntime[RunContext, AnalysisState]
) -> str:
    """Read the full text of a domain knowledge skill listed in your prompt."""
    skill = runtime.context.services.skills("knowledge").skills.get(name)
    return skill.body if skill else f"'{name}' 지식 skill이 없습니다."


def _lines(section: dict) -> str:
    rows = [
        f"- line_id={line['id']}: {line['text']}" for line in section["lines"]
    ]
    return "\n".join(rows) or "(비어 있음)"


async def _listing(ctx: RunContext, section: str) -> str:
    current = await ctx.services.memory.section(ctx.project_id, section)
    return (
        f"[{current['title']}] {len(current['content'])}/"
        f"{current['max_chars']}자\n{_lines(current)}"
    )


async def _memory_failed(
    ctx: RunContext, section: str, exc: MemoryEditError
) -> str:
    message = f"메모리 저장 실패: {exc}"
    if exc.status == 404 and section not in SECTIONS:
        return f"{message}. section은 {', '.join(SECTIONS)} 중 하나입니다."
    hint = (
        " 한도를 넘습니다. 기존 줄을 line_id로 바꾸거나(save_memory) "
        "지운 뒤(delete_memory) 다시 저장하세요."
        if exc.status == 422 and "exceeds" in str(exc)
        else ""
    )
    return f"{message}.{hint}\n{await _listing(ctx, section)}"


@tool
async def save_memory(
    section: Section,
    text: str,
    runtime: ToolRuntime[RunContext, AnalysisState],
    line_id: str | None = None,
    reason: str = "",
) -> str:
    """Save one line to the project memory shared by every session of this
    project. Only when the user explicitly asks to remember something.

    section: overview | preferences | core_interests | key_events.
    text: one Markdown line (key_events lines start with YYYY-MM-DD).
    line_id: replace that line instead of adding one. "?" changes nothing
    and lists the section's lines with their ids.
    """
    ctx = runtime.context
    if line_id == "?" and section in SECTIONS:
        return await _listing(ctx, section)
    actor = Actor(
        "agent",
        "main",
        ctx.session_id,
        ctx.run_id,
        {"session_id": ctx.session_id, "run_id": ctx.run_id, "reason": reason},
    )
    try:
        saved = await ctx.services.memory.save_line(
            ctx.project_id, section, text, actor=actor, line_id=line_id
        )
    except MemoryEditError as exc:
        return await _memory_failed(ctx, section, exc)
    if saved is None:
        return "이미 같은 내용이 저장되어 있습니다."
    await ctx.emit("memory_updated", updated_event(saved, "agent"))
    return f"메모리 저장: [{saved['title']}] v{saved['version']}"


@tool
async def delete_memory(
    section: Section,
    line_id: str,
    runtime: ToolRuntime[RunContext, AnalysisState],
) -> str:
    """Delete one line of project memory when the user asks for it.

    line_id "?" changes nothing and lists the section's lines with ids.
    """
    ctx = runtime.context
    if line_id == "?" and section in SECTIONS:
        return await _listing(ctx, section)
    try:
        saved = await ctx.services.memory.delete_line(
            ctx.project_id,
            section,
            line_id,
            actor=Actor("agent", "main", ctx.session_id, ctx.run_id),
        )
    except MemoryEditError as exc:
        return await _memory_failed(ctx, section, exc)
    if saved is not None:
        await ctx.emit("memory_updated", updated_event(saved, "agent"))
    return "삭제했습니다."


@tool
async def start_analysis(
    task: str, context: str, runtime: ToolRuntime[RunContext, AnalysisState]
) -> Command:
    """Hand the conversation to the analyst to plan and run data analysis code.

    task: what the user wants analysed, in your own words.
    context: only the domain facts / constraints / memory the analyst needs
    (it cannot read knowledge skills).
    """
    await runtime.context.emit(
        "agent_switched", {"agent": "analyst", "task": task}
    )
    message = (
        f"분석 담당으로 전환합니다.\n[과제]\n{task}\n"
        f"[참고 맥락]\n{context or '없음'}"
    )
    return Command(
        update={
            "active_agent": "analyst",
            # a new analysis plans anew: the last one's plan never carries
            # over (run_plan, save_workflow and the prompt read it)
            "plan": None,
            "messages": [
                ToolMessage(message, tool_call_id=runtime.tool_call_id)
            ],
        }
    )
