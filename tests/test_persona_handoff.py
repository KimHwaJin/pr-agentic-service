from types import SimpleNamespace

from langchain_core.messages import AIMessage, RemoveMessage

from src.dtest.agent.middleware.persona import (
    ANALYST_NUDGES,
    PersonaMiddleware,
)


class _Ctx:
    def __init__(self):
        self.events = []

    async def emit(self, kind, data):
        self.events.append((kind, data))


def _run(state):
    import asyncio

    ctx = _Ctx()
    middleware = PersonaMiddleware()
    runtime = SimpleNamespace(context=ctx)
    return asyncio.run(middleware.aafter_model(state, runtime)), ctx


def _state(message, agent="analyst", nudges=0, notice=None):
    return {
        "messages": [message],
        "active_agent": agent,
        "nudges": nudges,
        "notice": notice,
    }


def test_text_only_analyst_reply_is_sent_back():
    update, _ = _run(_state(AIMessage("확인 중이야, 기다려줘", id="m1")))
    assert update["jump_to"] == "model" and update["nudges"] == 1
    assert update["messages"] == [RemoveMessage(id="m1")]
    assert "확인 중이야" in update["notice"]


def test_main_takes_over_when_the_analyst_keeps_stalling():
    stalled = _state(AIMessage("곧 알려줄게", id="m2"), nudges=ANALYST_NUDGES)
    update, ctx = _run(stalled)
    assert update["active_agent"] == "main" and update["jump_to"] == "model"
    assert ctx.events == [("agent_switched", {"agent": "main"})]


def test_tool_calls_and_main_answers_end_normally():
    call = AIMessage(
        "", id="m3", tool_calls=[{"name": "run_plan", "args": {}, "id": "c1"}]
    )
    update, _ = _run(_state(call, nudges=1, notice="x"))
    assert update == {"notice": None, "nudges": 0}
    assert _run(_state(AIMessage("답변", id="m4"), agent="main"))[0] is None
