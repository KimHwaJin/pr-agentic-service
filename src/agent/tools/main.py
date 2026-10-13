"""Tools of the main (conversation) agent: domain knowledge, project memory, hand-off to analysis."""

from typing import Literal

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command, interrupt

from agent.context import AnalysisState, RunContext
from core.memory.service import Actor, MemoryError

Category = Literal["background", "analysis_preferences", "report_preferences", "shared_findings"]


@tool
async def read_knowledge(name: str, runtime: ToolRuntime[RunContext, AnalysisState]) -> str:
    """Read the full text of a domain knowledge skill listed in your prompt."""
    skill = runtime.context.services.skills("knowledge").skills.get(name)
    return skill.body if skill else f"'{name}' 지식 skill이 없습니다."


@tool
async def search_memory(query: str, runtime: ToolRuntime[RunContext, AnalysisState]) -> str:
    """Search project shared memory for entries related to the query (beyond those already in your prompt)."""
    ctx = runtime.context
    items = await ctx.services.memory.search(ctx.project_id, query, limit=8)
    if not items:
        return "관련 메모리가 없습니다."
    return "\n".join(f"- id={m['id']} v{m['version']} [{m['category']}] {m['title']}: {m['content']}" for m in items)


@tool
async def save_memory(
    category: Category,
    title: str,
    content: str,
    runtime: ToolRuntime[RunContext, AnalysisState],
    item_id: str | None = None,
    expected_version: int | None = None,
    reason: str = "",
) -> str:
    """Create or update a project memory entry shared by every session of this project.

    Update an existing entry (item_id + expected_version) instead of creating a near-duplicate.
    Entries written by the user (author=user) are changed only after the user approves.
    """
    ctx = runtime.context
    memory = ctx.services.memory
    actor = Actor("agent", "main", ctx.session_id, ctx.run_id)
    source = {"session_id": ctx.session_id, "run_id": ctx.run_id, "reason": reason}
    try:
        if item_id is None:
            similar = [
                m for m in await memory.search(ctx.project_id, f"{title} {content}", 1) if (m["score"] or 0) >= 0.9
            ]
            if similar:
                m = similar[0]
                return f"비슷한 항목이 이미 있습니다. 이 항목을 갱신하세요: id={m['id']} v{m['version']} {m['title']}: {m['content']}"
            item = await memory.create(
                ctx.project_id, category=category, title=title, content=content, actor=actor, source=source
            )
            action = "created"
        else:
            current = await memory.get(ctx.project_id, item_id)
            if current is None:
                return f"메모리 항목 {item_id}가 없습니다."
            approved = False
            if current["author"] == "user":
                answer = interrupt(
                    {
                        "type": "memory_change",
                        "item": current,
                        "proposed": {"category": category, "title": title, "content": content},
                        "reason": reason,
                    }
                )
                if not (isinstance(answer, dict) and answer.get("approve")):
                    return "사용자가 메모리 변경을 거절했습니다. 이번 요청에만 반영하세요."
                approved = True
            item = await memory.update(
                ctx.project_id,
                item_id,
                expected_version=expected_version if expected_version is not None else current["version"],
                actor=actor,
                title=title,
                content=content,
                category=category,
                approved_by_user=approved,
            )
            action = "updated"
    except MemoryError as exc:
        return f"메모리 저장 실패: {exc}"
    await ctx.emit("memory_updated", {"action": action, "item": item})
    return f"메모리 {action}: id={item['id']} v{item['version']}"


@tool
async def delete_memory(item_id: str, expected_version: int, runtime: ToolRuntime[RunContext, AnalysisState]) -> str:
    """Delete an agent-written project memory entry that became wrong or obsolete."""
    ctx = runtime.context
    try:
        await ctx.services.memory.delete(
            ctx.project_id,
            item_id,
            expected_version=expected_version,
            actor=Actor("agent", "main", ctx.session_id, ctx.run_id),
        )
    except MemoryError as exc:
        return f"메모리 삭제 실패: {exc}"
    await ctx.emit("memory_updated", {"action": "deleted", "item": {"id": item_id}})
    return "삭제했습니다."


@tool
async def start_analysis(task: str, context: str, runtime: ToolRuntime[RunContext, AnalysisState]) -> Command:
    """Hand the conversation to the analyst to plan and run data analysis code.

    task: what the user wants analysed, in your own words.
    context: only the domain facts / constraints / memory the analyst needs (it cannot read knowledge skills).
    """
    await runtime.context.emit("agent_switched", {"agent": "analyst", "task": task})
    message = f"분석 담당으로 전환합니다.\n[과제]\n{task}\n[참고 맥락]\n{context or '없음'}"
    return Command(
        update={
            "active_agent": "analyst",
            "messages": [ToolMessage(message, tool_call_id=runtime.tool_call_id)],
        }
    )
