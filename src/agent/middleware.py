"""One agent graph, two personas (main / analyst) switched by tool hand-offs.

Per model call this middleware picks the active persona's Markdown prompt,
exposes only that persona's tools, injects project instructions + project
memory (never stored in the message history) and hides the other persona's
catalog reads so neither carries skills it does not need.
"""

import json
from collections.abc import Awaitable, Callable
from typing import Any, cast

import json_repair
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from agent.context import AnalysisState, RunContext
from agent.prompts import Prompt, load_prompt
from core.memory.service import render_for_prompt
from core.workflows import spec

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
        return {"active_agent": state.get("active_agent") or "main"}

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
                messages=_isolate(request.messages, persona),
            )
        )


def _plan_status(state: AnalysisState) -> str:
    plan, execution = state.get("plan"), state.get("execution")
    if not plan:
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
