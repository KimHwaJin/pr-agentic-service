import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Collection
from dataclasses import dataclass
from typing import Any, cast

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
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

from src.dtest.agent.context import AnalysisState, RunContext
from src.dtest.agent.llm import chat_model
from src.dtest.agent.middleware import (
    JsonArgumentsMiddleware,
    PersonaMiddleware,
    ReportingSummarizationMiddleware,
    ToolFailureLimitMiddleware,
    compaction_rules,
)
from src.dtest.agent.prompts import load_prompt
from src.dtest.agent.tools.analysis import (
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
from src.dtest.agent.tools.common import ask_user
from src.dtest.agent.tools.main import (
    delete_memory,
    read_knowledge,
    save_memory,
    start_analysis,
)
from src.dtest.core.config import Settings
from src.dtest.core.events import TokenBuffer
from src.dtest.core.executor.client import ExecutorError

log = logging.getLogger(__name__)

TOOLS = [
    ask_user,
    read_knowledge,
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
                PersonaMiddleware(),
                JsonArgumentsMiddleware(),
                ToolFailureLimitMiddleware(
                    self.settings.agent_tool_failure_limit
                ),
                ToolErrorMiddleware(on_error=tool_error),
                ModelCallLimitMiddleware(
                    run_limit=self.settings.agent_model_call_limit,
                    exit_behavior="end",
                ),
            ]
            if self.settings.agent_compact_finished_analysis:
                middleware.append(compaction_rules.finished_analysis())
            trigger = self.settings.agent_summary_trigger_tokens
            middleware.append(
                ReportingSummarizationMiddleware(
                    model,
                    trigger=("tokens", trigger),
                    # by tokens, so a summary always lands below the trigger
                    # (a message count can stay above it and re-summarize on
                    # every call)
                    keep=("tokens", trigger // 2),
                    summary_prompt=load_prompt("summary").render(
                        max_chars=self.settings.agent_summary_max_chars
                    ),
                    trim_tokens_to_summarize=None,  # summarize all of it
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
            if command is None:
                # The API checks the id against run.waiting; a checkpoint
                # without it (already answered on a pod that died before
                # recording it) continues from the checkpoint, which asks
                # again if the question is still open.
                log.warning(
                    "resume_interrupt_not_pending run_id=%s interrupt=%s "
                    "pending=%s",
                    ctx.run_id,
                    resume["interrupt_id"],
                    ",".join(pending),
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

        await relay(
            graph.astream(
                command,
                config,
                context=ctx,
                stream_mode=["messages", "updates"],
                durability="async",
            ),
            ctx.emit,
            quiet=QUIET_TOOLS,
        )

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
        text = last.text if last else ""
        if not text.strip() or text.startswith(LIMIT_PREFIX):
            # ModelCallLimitMiddleware ended the turn (its message is an
            # English note), or the model said nothing: the user still gets
            # an answer
            text = STOPPED_ANSWER
        return TurnResult(None, text)


LIMIT_PREFIX = "Model call limits exceeded"
STOPPED_ANSWER = (
    "요청을 처리하는 단계가 너무 많아져 중간에 멈췄습니다. 지금까지의 진행 "
    "내용은 남아 있으니 '계속'이라고 보내 이어서 진행하거나, 질문을 나눠서 "
    "다시 요청해 주세요."
)


def tool_error(exc: Exception, request: Any) -> str:
    """Executor/validation problems go back to the model.

    The model can then adapt instead of failing the run.
    """
    if isinstance(exc, ExecutorError):
        # the model may quote it to the user: the error code and message
        # only, not the whole response body
        error = exc.body.get("error") if isinstance(exc.body, dict) else None
        if isinstance(error, dict):
            detail = f"{error.get('code')}: {error.get('message', '')}"
        else:
            detail = str(exc.body)
        return f"executor 오류 {exc.status}: {detail[:500]}"
    message = f"도구 실행 오류 ({type(exc).__name__}): {exc}"
    if isinstance(exc, TypeError) and "argument" in str(exc):
        # the call did not match the function: say what it takes
        schema = getattr(getattr(request, "tool", None), "args", None) or {}
        if schema:
            message += f"\n이 도구의 인자: {', '.join(schema)}"
    return message


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


async def relay(
    stream: AsyncIterator[tuple[str, Any]],
    emit: Callable[..., Awaitable[None]],
    quiet: Collection[str] = (),
) -> dict[str, Any]:
    """Send a graph stream's token deltas and tool calls as events.

    Returns the last ``values`` chunk when the stream carries them.
    """
    tokens = TokenBuffer(emit)
    state: dict[str, Any] = {}
    async for mode, chunk in stream:
        if mode == "values":
            state = chunk
        elif mode == "messages":
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
                    if call["name"] not in quiet:
                        await emit(
                            "tool_call",
                            {
                                "name": call["name"],
                                "args": brief_args(call["args"]),
                            },
                        )
    await tokens.flush()
    return state


def brief_args(args: dict[str, Any], limit: int = 600) -> dict[str, Any]:
    return {
        k: (v if len(repr(v)) <= limit else repr(v)[:limit] + "...")
        for k, v in args.items()
    }
