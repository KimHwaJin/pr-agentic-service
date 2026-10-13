"""One agent graph, two personas (main / analyst) switched by tool hand-offs.

Per model call this middleware picks the active persona's Markdown prompt,
exposes only that persona's tools, injects project instructions + project
memory (never stored in the message history) and hides the other persona's
catalog reads so neither carries skills it does not need.

A turn ends when a model reply has no tool calls. That is the main agent's
answer; the analyst must hand back with finish_analysis. A text-only analyst
reply is dropped and the analyst is told to carry on; if it keeps doing that,
the main agent takes over and explains the situation, so a turn never stops
on a half-done hand-off.
"""

import json
from collections.abc import Awaitable, Callable
from typing import Any, cast

import json_repair
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    hook_config,
)
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)

from agent.context import AnalysisState, RunContext
from agent.prompts import Prompt, load_prompt
from core.memory.service import render_for_prompt
from core.workflows import spec

# text-only analyst replies sent back before the main agent takes over
ANALYST_NUDGES = 2

PERSONA_TOOLS = {
    "main": {
        "ask_user",
        "read_knowledge",
        "search_memory",
        "save_memory",
        "delete_memory",
        "start_analysis",
    },
    "analyst": {
        "ask_user",
        "read_skill",
        "read_tool",
        "search_tools",
        "search_workflows",
        "propose_plans",
        "revise_call",
        "run_plan",
        "run_custom_code",
        "write_report",
        "save_workflow",
        "finish_analysis",
    },
}
# Tool results that only matter to the persona that asked for them.
PRIVATE_RESULTS = {
    "main": {"read_knowledge"},
    "analyst": {"read_skill", "read_tool", "search_tools", "search_workflows"},
}
CODE_LEVELS = {
    1: (
        "1 (tools_only): 등록된 tool 선택과 인자 결정만 가능. "
        "run_custom_code 사용 불가."
    ),
    2: (
        "2 (tools_with_glue): tool 사이 짧은 연결 코드"
        "(컬럼 선택, 형변환, 필터)만 run_custom_code로 작성 가능."
    ),
    3: (
        "3 (tools_first): tool 우선. "
        "맞는 tool이 없거나 실패를 메울 때 새 함수를 작성 가능."
    ),
    4: "4 (free_code): tool은 참고만 하고 필요한 코드를 자유롭게 작성 가능.",
}


class PersonaMiddleware(AgentMiddleware[AnalysisState, RunContext]):
    state_schema = AnalysisState

    def __init__(self, prompts_root):
        super().__init__()
        self.prompts_root = prompts_root

    def _prompt(self, name: str) -> Prompt:
        return load_prompt(
            self.prompts_root, name
        )  # read per call: edits apply without a restart

    async def abefore_agent(
        self, state: AnalysisState, runtime
    ) -> dict[str, Any] | None:
        ctx: RunContext = runtime.context
        memory = ctx.services.memory
        settings = ctx.services.settings
        index = await memory.entries(ctx.project_id)
        relevant = (
            await memory.search(
                ctx.project_id, ctx.user_text, settings.memory_prompt_items
            )
            if index
            else []
        )
        ctx.cache["memory"] = render_for_prompt(
            index, relevant, settings.memory_prompt_max_chars
        )
        return {
            "active_agent": state.get("active_agent") or "main",
            "nudges": 0,
            "notice": None,
        }

    @hook_config(can_jump_to=["model"])
    async def aafter_model(
        self, state: AnalysisState, runtime
    ) -> dict[str, Any] | None:
        last = state["messages"][-1]
        if not isinstance(last, AIMessage):
            return None
        if last.tool_calls:
            if state.get("notice") or state.get("nudges"):
                return {"notice": None, "nudges": 0}
            return None
        if state.get("active_agent") != "analyst" or last.id is None:
            return None
        # The analyst answered without a tool: without this the turn ends
        # here, on a promise nobody will keep.
        nudges = state.get("nudges", 0)
        update: dict[str, Any] = {
            "messages": [RemoveMessage(id=last.id)],
            "jump_to": "model",
        }
        if nudges < ANALYST_NUDGES:
            notice = self._prompt("analyst_continue").render(last=last.text)
            return {**update, "nudges": nudges + 1, "notice": notice}
        ctx: RunContext = runtime.context
        await ctx.emit("agent_switched", {"agent": "main"})
        notice = self._prompt("main_fallback").render(last=last.text)
        return {
            **update,
            "active_agent": "main",
            "nudges": 0,
            "notice": notice,
        }

    async def aafter_agent(
        self, state: AnalysisState, runtime
    ) -> dict[str, Any] | None:
        return {
            "active_agent": "main"
        }  # every new user turn starts with the main agent

    async def awrap_model_call(
        self,
        request: ModelRequest[RunContext],
        handler: Callable[
            [ModelRequest[RunContext]], Awaitable[ModelResponse]
        ],
    ) -> ModelResponse:
        ctx = request.runtime.context
        persona = request.state.get("active_agent") or "main"
        prompt = self._prompt(persona)
        allowed = set(PERSONA_TOOLS[persona])
        if ctx.code_level < 2:
            allowed.discard("run_custom_code")
        skills = "\n\n".join(
            ctx.services.skills(root).index() for root in prompt.skills
        )
        system = prompt.render(
            skills=skills or "없음",
            code_level=CODE_LEVELS[ctx.code_level],
            plan=_plan_status(cast(AnalysisState, request.state)),
            plan_candidates=ctx.services.settings.plan_candidates,
        )
        extras = [
            f"# 프로젝트 지침 (사용자가 작성)\n{ctx.project_prompt}"
            if ctx.project_prompt
            else "",
            ctx.cache.get("memory", ""),
        ]
        system = "\n\n".join([system, *filter(None, extras)])
        return await handler(
            request.override(
                system_message=SystemMessage(system),
                tools=[
                    t
                    for t in request.tools
                    if getattr(t, "name", None) in allowed
                ],
                messages=[
                    *await _with_images(
                        _isolate(request.messages, persona), ctx
                    ),
                    *_notice(request.state),
                ],
            )
        )


async def _with_images(messages: list, ctx: RunContext) -> list:
    """Image references in user turns -> image data for this model call.

    The checkpoint keeps only ``{"type": "image", "file_id": <image id>}``.
    Images of the last ``image_context_turns`` user turns are sent when the
    model accepts images; older ones (or a text-only model) get a short
    text placeholder instead.
    """
    settings = ctx.services.settings
    spec = settings.model(ctx.model)
    vision = bool(spec and spec.vision)
    turns = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
    recent = set(turns[-settings.image_context_turns :])
    out = []
    for i, message in enumerate(messages):
        content = message.content
        if not isinstance(message, HumanMessage) or not isinstance(
            content, list
        ):
            out.append(message)
            continue
        blocks: list[Any] = []
        for block in content:
            if not (
                isinstance(block, dict)
                and block.get("type") == "image"
                and block.get("file_id")
            ):
                blocks.append(block)
                continue
            name = (block.get("extras") or {}).get("name") or "이미지"
            data = (
                await _image_data(ctx, block["file_id"])
                if vision and i in recent
                else None
            )
            if data:
                blocks.append(
                    {
                        "type": "image",
                        "base64": data,
                        "mime_type": block.get("mime_type"),
                    }
                )
            else:
                blocks.append({"type": "text", "text": f"[이미지: {name}]"})
        out.append(message.model_copy(update={"content": blocks}))
    return out


async def _image_data(ctx: RunContext, image_id: str) -> str | None:
    cache = ctx.cache.setdefault("images", {})
    if image_id not in cache:
        image = await ctx.services.images.get(image_id)
        cache[image_id] = (
            ctx.services.images.read_base64(image)
            if image is not None and image.session_id == ctx.session_id
            else None
        )
    return cache[image_id]


def _notice(state: Any) -> list[HumanMessage]:
    notice = state.get("notice")
    return [HumanMessage(notice)] if notice else []


def _plan_status(state: AnalysisState) -> str:
    plan, execution = state.get("plan"), state.get("execution")
    if not plan or not plan.get("document"):
        return "승인된 계획 없음"
    calls = {
        f"#{i} {c.tool}": plan["calls"][c.key]["status"]
        for i, c in enumerate(spec.calls(plan["document"]))
    }
    kernel = (
        "살아 있음(변수 재사용 가능)"
        if execution and execution.get("alive")
        else "없음(다음 실행 시 새 커널)"
    )
    status = json.dumps(calls, ensure_ascii=False)
    return f"계획: {plan['title']}\n호출 상태: {status}\n커널: {kernel}"


def _isolate(messages: list, persona: str) -> list:
    hidden_tools = set().union(
        *(names for p, names in PRIVATE_RESULTS.items() if p != persona)
    )
    hidden_ids = {
        call["id"]
        for m in messages
        if isinstance(m, AIMessage)
        for call in m.tool_calls
        if call["name"] in hidden_tools
    }
    out = []
    for m in messages:
        if isinstance(m, ToolMessage) and m.tool_call_id in hidden_ids:
            m = m.model_copy(
                update={"content": "(다른 담당자가 참고한 자료라 생략)"}
            )
        out.append(m)
    return out


class JsonArgumentsMiddleware(AgentMiddleware):
    """Decodes nested arguments that arrive as JSON strings.

    Some served models (vLLM tool parsers) send nested object/array
    arguments as JSON strings. Decode them before validation instead of
    letting the model retry the same call.
    """

    async def awrap_tool_call(self, request, handler):
        schema = getattr(request.tool, "tool_call_schema", None)
        properties = (
            schema.model_json_schema().get("properties", {}) if schema else {}
        )
        args = request.tool_call.get("args") or {}
        fixed = {}
        for name, value in args.items():
            if isinstance(value, str) and _structured(
                properties.get(name, {})
            ):
                try:
                    fixed[name] = json.loads(value)
                except ValueError:
                    repaired = json_repair.loads(
                        value
                    )  # unbalanced braces etc.
                    if isinstance(repaired, (dict, list)):
                        fixed[name] = repaired
        if fixed:
            request = request.override(
                tool_call={**request.tool_call, "args": {**args, **fixed}}
            )
        return await handler(request)


def _structured(prop: dict) -> bool:
    options = prop.get("anyOf", [prop])
    return any(option.get("type") in {"object", "array"} for option in options)
