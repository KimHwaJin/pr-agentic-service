"""Tools of the main (conversation) agent.

Domain knowledge, project memory, hand-off to analysis.
"""

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from agent.context import AnalysisState, RunContext
from core.memory.service import (
    Actor,
    MemoryEditError,
    render_topic_index,
    updated_event,
)


@tool
async def read_knowledge(
    name: str, runtime: ToolRuntime[RunContext, AnalysisState]
) -> str:
    """Read the full text of a domain knowledge skill listed in your prompt."""
    skill = runtime.context.services.skills("knowledge").skills.get(name)
    return skill.body if skill else f"'{name}' 지식 skill이 없습니다."


def _lines(content: dict) -> str:
    rows = [
        f"- line_id={line['id']}: {line['text']}" for line in content["lines"]
    ]
    return "\n".join(rows) or "(비어 있음)"


async def _topics(ctx: RunContext) -> str:
    topics = await ctx.services.memory.topics(ctx.project_id)
    return (
        f"메모리 주제 (topic id: 제목 — 설명):\n{render_topic_index(topics)}"
    )


async def _resolve(ctx: RunContext, topic: str) -> str | None:
    """A topic id, also accepting the title the model saw in the prompt."""
    topics = await ctx.services.memory.topics(ctx.project_id)
    wanted = topic.strip().casefold()
    for t in topics:
        if wanted in (t["id"].casefold(), t["title"].casefold()):
            return t["id"]
    return None


async def _listing(ctx: RunContext, topic_id: str) -> str:
    current = await ctx.services.memory.content(ctx.project_id, topic_id)
    return (
        f"[{current['title']}] (topic={topic_id}) "
        f"{len(current['content'])}/{current['max_chars']}자\n"
        f"{_lines(current)}"
    )


async def _memory_failed(
    ctx: RunContext, topic_id: str, exc: MemoryEditError
) -> str:
    message = f"메모리 저장 실패: {exc}"
    if exc.status == 404 and "topic" in str(exc):
        return f"{message}.\n{await _topics(ctx)}"
    hint = (
        " 한도를 넘습니다. 기존 줄을 line_id로 바꾸거나(save_memory) "
        "지운 뒤(delete_memory) 다시 저장하세요."
        if exc.status == 422 and "exceeds" in str(exc)
        else ""
    )
    return f"{message}.{hint}\n{await _listing(ctx, topic_id)}"


@tool
async def save_memory(
    topic: str,
    runtime: ToolRuntime[RunContext, AnalysisState],
    text: str = "",
    line_id: str | None = None,
    reason: str = "",
) -> str:
    """Save one line to the project memory shared by every session of this
    project. Only when the user explicitly asks to remember something.

    topic: a memory topic id. "?" changes nothing and lists the project's
    topics (id, title, description, limit); put the line only where it
    fits a topic's title and description.
    text: one Markdown line, following the topic's description.
    line_id: replace that line instead of adding one. "?" changes nothing
    and lists the topic's lines with their ids.
    """
    ctx = runtime.context
    topic_id = None if topic.strip() == "?" else await _resolve(ctx, topic)
    if topic_id is None:
        prefix = (
            "" if topic.strip() == "?" else f"'{topic}' 주제가 없습니다.\n"
        )
        return prefix + await _topics(ctx)
    if line_id == "?":
        return await _listing(ctx, topic_id)
    actor = Actor(
        "agent",
        "main",
        ctx.session_id,
        ctx.run_id,
        {"session_id": ctx.session_id, "run_id": ctx.run_id, "reason": reason},
    )
    try:
        saved = await ctx.services.memory.save_line(
            ctx.project_id, topic_id, text, actor=actor, line_id=line_id
        )
    except MemoryEditError as exc:
        return await _memory_failed(ctx, topic_id, exc)
    if saved is None:
        return "이미 같은 내용이 저장되어 있습니다."
    await ctx.emit("memory_updated", updated_event(saved, "agent"))
    return f"메모리 저장: [{saved['title']}] v{saved['version']}"


@tool
async def delete_memory(
    topic: str,
    line_id: str,
    runtime: ToolRuntime[RunContext, AnalysisState],
) -> str:
    """Delete one line of project memory when the user asks for it.

    topic "?" lists the project's topics with ids; line_id "?" changes
    nothing and lists the topic's lines with ids.
    """
    ctx = runtime.context
    topic_id = None if topic.strip() == "?" else await _resolve(ctx, topic)
    if topic_id is None:
        prefix = (
            "" if topic.strip() == "?" else f"'{topic}' 주제가 없습니다.\n"
        )
        return prefix + await _topics(ctx)
    if line_id == "?":
        return await _listing(ctx, topic_id)
    try:
        saved = await ctx.services.memory.delete_line(
            ctx.project_id,
            topic_id,
            line_id,
            actor=Actor("agent", "main", ctx.session_id, ctx.run_id),
        )
    except MemoryEditError as exc:
        return await _memory_failed(ctx, topic_id, exc)
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
