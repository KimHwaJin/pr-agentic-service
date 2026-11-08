"""One model response, repeated tool calls: identical calls run once and
propose_plans calls become one card."""

import asyncio
import json
from typing import NotRequired

from langchain.agents import AgentState, create_agent
from langchain.tools import ToolRuntime
from langchain_core.language_models.fake_chat_models import (
    GenericFakeChatModel,
)
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt

from agent.middleware import ToolCallDedupMiddleware
from agent.middleware.tool_call_dedup import dedup_message


def _call(name, id, **args):
    return {"name": name, "args": args, "id": id, "type": "tool_call"}


def _ids(message):
    return [c["id"] for c in message.tool_calls]


def test_identical_calls_run_once_and_others_stay():
    message = AIMessage(
        "",
        tool_calls=[
            _call("read_tool", "a", names=["x", "y"]),
            _call("read_tool", "b", names=["x", "y"]),
            _call("read_tool", "c", names=["z"]),
            _call("search_workflows", "d", query="q"),
        ],
    )
    assert _ids(dedup_message(message)) == ["a", "c", "d"]


def test_nothing_repeated_keeps_the_message():
    message = AIMessage(
        "",
        tool_calls=[_call("read_skill", "a", skill="s"), _call("x", "b")],
    )
    assert dedup_message(message) is message


def test_propose_plans_calls_merge_into_the_first():
    message = AIMessage(
        "",
        tool_calls=[
            _call("propose_plans", "p1", candidates=[{"title": "A"}]),
            _call("read_tool", "r", names=["x"]),
            # some served models send list arguments as JSON strings
            _call(
                "propose_plans",
                "p2",
                candidates=json.dumps([{"title": "B"}, {"title": "A"}]),
            ),
        ],
    )
    out = dedup_message(message)
    assert _ids(out) == ["p1", "r"]
    assert out.tool_calls[0]["args"]["candidates"] == [
        {"title": "A"},
        {"title": "B"},
        {"title": "A"},  # propose_plans drops the repeated plan
    ]
    assert message.tool_calls[0]["args"]["candidates"] == [{"title": "A"}]


class _Model(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class _State(AgentState):
    plan: NotRequired[dict | None]


@tool
def propose_plans(candidates: list[dict], runtime: ToolRuntime) -> Command:
    """Show the candidates and wait for one."""
    choice = interrupt({"type": "plan_approval", "candidates": candidates})
    return Command(
        update={
            "plan": {"choice": choice},
            "messages": [ToolMessage("ok", tool_call_id=runtime.tool_call_id)],
        }
    )


def _agent(middleware):
    responses = iter(
        [
            AIMessage(
                "",
                tool_calls=[
                    _call("propose_plans", "p1", candidates=[{"t": "A"}]),
                    _call("propose_plans", "p2", candidates=[{"t": "B"}]),
                ],
            ),
            AIMessage("done"),
        ]
    )
    return create_agent(
        _Model(messages=responses),
        tools=[propose_plans],
        middleware=middleware,
        state_schema=_State,
        checkpointer=InMemorySaver(),
    )


async def _approve_all(graph) -> tuple[int, dict]:
    config = {"configurable": {"thread_id": "t"}}
    await graph.ainvoke(
        {"messages": [{"role": "user", "content": "q"}]}, config
    )
    cards = 0
    while (state := await graph.aget_state(config)).interrupts:
        cards += 1
        first = state.interrupts[0]
        await graph.ainvoke(Command(resume={first.id: "approve"}), config)
    return cards, state.values


def test_one_card_for_two_propose_plans_calls():
    cards, values = asyncio.run(
        _approve_all(_agent([ToolCallDedupMiddleware()]))
    )
    assert cards == 1
    assert values["plan"] == {"choice": "approve"}
    assert values["messages"][-1].text == "done"


def test_without_it_the_second_card_fails_the_turn():
    """What the middleware prevents (LangGraph refuses two plan writes)."""
    import pytest
    from langgraph.errors import InvalidUpdateError

    with pytest.raises(InvalidUpdateError):
        asyncio.run(_approve_all(_agent([])))
