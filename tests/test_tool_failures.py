import asyncio

from langchain.agents import create_agent
from langchain.agents.middleware import ToolErrorMiddleware
from langchain_core.language_models.fake_chat_models import (
    GenericFakeChatModel,
)
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from agent.graph import tool_error
from agent.middleware.tool_failures import (
    STOPPED,
    ToolFailureLimitMiddleware,
    failure_streak,
)


def _call(n: int, name: str = "run_plan") -> AIMessage:
    return AIMessage(
        "", tool_calls=[{"name": name, "args": {}, "id": f"c{n}"}]
    )


def _result(n: int, content: str, status: str = "error", name="run_plan"):
    return ToolMessage(content, tool_call_id=f"c{n}", name=name, status=status)


def _error(n: int) -> str:
    # what changed between the real retries: folder number and pid
    return (
        "도구 실행 오류 (FileNotFoundError): [Errno 2] No such file: "
        f"'runs/{n:02d}-run_plan/.00-setup.py.{4000 + n}.tmp'"
    )


def test_same_error_with_new_numbers_is_one_streak():
    messages = [HumanMessage("분석해줘")]
    for n in range(1, 4):
        messages += [_call(n), _result(n, _error(n))]
    count, error = failure_streak(messages, "run_plan")
    assert count == 3 and "03-run_plan" in error


def test_success_or_another_error_starts_over():
    base = [HumanMessage("q"), _call(1), _result(1, _error(1))]
    ok = base + [_call(2), _result(2, "완료", "success")]
    assert failure_streak(ok, "run_plan")[0] == 0
    other = base + [_call(2), _result(2, "executor 오류 422: bad")]
    assert failure_streak(other, "run_plan")[0] == 1
    # other tools do not break it; a new user turn does
    mixed = base + [_call(2, "read_skill"), _result(2, "ok", "success", "x")]
    mixed += [_call(3), _result(3, _error(3))]
    assert failure_streak(mixed, "run_plan")[0] == 2
    assert failure_streak(mixed + [HumanMessage("다시")], "run_plan")[0] == 0


def test_stops_do_not_break_the_streak():
    messages = [HumanMessage("q")]
    for n in range(1, 4):
        messages += [_call(n), _result(n, _error(n))]
    messages += [_call(4), _result(4, f"{STOPPED} 그만")]
    assert failure_streak(messages, "run_plan")[0] == 3


class _Model(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def test_the_agent_stops_running_a_tool_that_keeps_failing():
    runs = []

    @tool
    def run_plan() -> str:
        """Runs the plan."""
        runs.append(1)
        raise FileNotFoundError(f"runs/{len(runs):02d}-run_plan/x.tmp")

    model = _Model(
        messages=iter(
            [_call(n) for n in range(1, 6)] + [AIMessage("저장 실패로 중단")]
        ),
        disable_streaming=True,
    )
    agent = create_agent(
        model,
        tools=[run_plan],
        middleware=[
            ToolFailureLimitMiddleware(3),
            ToolErrorMiddleware(on_error=tool_error),
        ],
    )
    state = asyncio.run(
        agent.ainvoke({"messages": [HumanMessage("분석해줘")]})
    )
    assert len(runs) == 3  # the 4th and 5th calls never ran
    results = [m for m in state["messages"] if isinstance(m, ToolMessage)]
    assert [str(m.content).startswith(STOPPED) for m in results] == [
        False,
        False,
        False,
        True,
        True,
    ]
    assert "3번 연속" in str(results[3].content)
    assert state["messages"][-1].content == "저장 실패로 중단"
