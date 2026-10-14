from dataclasses import dataclass
from typing import Any, cast

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    SummarizationMiddleware,
    ToolErrorMiddleware,
)
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    ToolMessage,
)
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore
from langgraph.types import Command

from agent import compaction_rules
from agent.context import AnalysisState, RunContext
from agent.llm import chat_model
from agent.middleware import JsonArgumentsMiddleware, PersonaMiddleware
from agent.tools.analysis import (
    finish_analysis,
    propose_plans,
    read_skill,
    read_tool,
    revise_call,
    run_custom_code,
    run_plan,
    save_workflow,
    search_tools,
    search_workflows,
    write_report,
)
from agent.tools.common import ask_user
from agent.tools.main import (
    delete_memory,
    read_knowledge,
    save_memory,
    search_memory,
    start_analysis,
)
from core.config import Settings
from core.events import TokenBuffer
from core.executor.client import ExecutorError

TOOLS = [
    ask_user,
    read_knowledge,
    search_memory,
    save_memory,
    delete_memory,
    start_analysis,
    read_skill,
    read_tool,
    search_tools,
    search_workflows,
    propose_plans,
    revise_call,
    run_plan,
    run_custom_code,
    write_report,
    save_workflow,
    finish_analysis,
]
QUIET_TOOLS = {"ask_user"}  # the HITL card itself is the visible event


@dataclass
class TurnResult:
    interrupt: dict[str, Any] | None  # {"id", "value"} when the run must wait
    answer: str | None


class AgentGraphs:
    """One compiled graph per served model name.

    All graphs share the checkpointer and store.
    """

    def __init__(
        self,
        settings: Settings,
        checkpointer: BaseCheckpointSaver,
        store: BaseStore,
    ):
        self.settings, self.checkpointer, self.store = (
            settings,
            checkpointer,
            store,
        )
        self._graphs: dict[str, Any] = {}

    def get(self, name: str):
        if name not in self._graphs:
            model = chat_model(self.settings, name)
            middleware: list[AgentMiddleware[Any, Any, Any]] = [
                PersonaMiddleware(self.settings.prompts_root),
                JsonArgumentsMiddleware(),
                ToolErrorMiddleware(on_error=_tool_error),
                ModelCallLimitMiddleware(
                    run_limit=self.settings.agent_model_call_limit,
                    exit_behavior="end",
                ),
            ]
            if self.settings.agent_compact_finished_analysis:
                middleware.append(compaction_rules.finished_analysis())
            middleware.append(
                SummarizationMiddleware(
                    model, trigger=("tokens", 60000), keep=("messages", 40)
                )
            )
            self._graphs[name] = create_agent(
                model,
                tools=TOOLS,
                middleware=middleware,
                state_schema=AnalysisState,
                context_schema=RunContext,
                checkpointer=self.checkpointer,
                store=self.store,
            )
        return self._graphs[name]

    async def run_turn(
        self, ctx: RunContext, resume: dict[str, Any] | None
    ) -> TurnResult:
        """Start (or continue after a crash) the turn for ctx.run_id.

        With ``resume``, resumes its pending interrupt instead.
        """
        graph = self.get(ctx.model)
        config = {
            "configurable": {"thread_id": ctx.session_id},
            "recursion_limit": self.settings.agent_recursion_limit,
        }
        state = await graph.aget_state(config)
        pending = {i.id for i in state.interrupts}
        if resume is not None:
            command = (
                Command(resume={resume["interrupt_id"]: resume["value"]})
                if resume["interrupt_id"] in pending
                else None
            )
        elif any(
            getattr(m, "id", None) == ctx.run_id
            for m in state.values.get("messages", [])
        ):
            # The turn already started on another pod: continue from its
            # checkpoint.
            command = None
        else:
            # A previous turn may have been cancelled while a tool was
            # waiting: close its tool calls.
            closing = _dangling_tool_results(state.values.get("messages", []))
            command = {
                "messages": [
                    *closing,
                    HumanMessage(
                        content=cast(Any, ctx.user_content or ctx.user_text),
                        id=ctx.run_id,
                    ),
                ]
            }

        tokens = TokenBuffer(ctx.services.events, ctx.session_id, ctx.run_id)
        stream = graph.astream(
            command,
            config,
            context=ctx,
            stream_mode=["messages", "updates"],
            durability="async",
        )
        async for mode, chunk in stream:
            if mode == "messages":
                message, meta = chunk
                if (
                    isinstance(message, AIMessageChunk)
                    and meta.get("langgraph_node") == "model"
                    and message.text
                ):
                    tokens.add(message.text)
            elif "model" in chunk:
                # keep token text ahead of the events that follow it
                await tokens.flush()
                for message in chunk["model"].get("messages", []):
                    for call in getattr(message, "tool_calls", []):
                        if call["name"] not in QUIET_TOOLS:
                            await ctx.emit(
                                "tool_call",
                                {
                                    "name": call["name"],
                                    "args": _brief(call["args"]),
                                },
                            )
        await tokens.flush()

        state = await graph.aget_state(config)
        if state.interrupts:
            first = state.interrupts[0]
            return TurnResult({"id": first.id, "value": first.value}, None)
        last = next(
            (
                m
                for m in reversed(state.values["messages"])
                if isinstance(m, AIMessage)
            ),
            None,
        )
        return TurnResult(None, last.text if last else "")


def _tool_error(exc: Exception, request: Any) -> str:
    """Executor/validation problems go back to the model.

    The model can then adapt instead of failing the run.
    """
    if isinstance(exc, ExecutorError):
        return f"executor 오류 {exc.status}: {exc.body}"
    return f"도구 실행 오류 ({type(exc).__name__}): {exc}"


def _dangling_tool_results(messages: list) -> list[ToolMessage]:
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    last_ai = next(
        (m for m in reversed(messages) if isinstance(m, AIMessage)), None
    )
    calls = last_ai.tool_calls if last_ai else []
    return [
        ToolMessage("사용자가 이전 작업을 취소했습니다.", tool_call_id=c["id"])
        for c in calls
        if c["id"] not in answered
    ]


def _brief(args: dict[str, Any], limit: int = 600) -> dict[str, Any]:
    return {
        k: (v if len(repr(v)) <= limit else repr(v)[:limit] + "...")
        for k, v in args.items()
    }
