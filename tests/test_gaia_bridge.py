import json
from types import SimpleNamespace

import pytest

from src.dtest.api_service.services import hitl
from src.dtest.core.db import Base
from src.dtest.gaia_bridge import auto_replies, graph, runtime
from src.dtest.gaia_bridge.turn import Transcript, _Follow

PLAN = {
    "type": "plan_approval",
    "interrupt_id": "i1",
    "candidates": [
        {
            "title": "NCE 탐색",
            "input_values": {"0.0.lot_cd": "A1"},
            "input_slots": [{"key": "0.0.lot_cd", "required": True}],
            "calls": [
                {
                    "params": [
                        {"key": "0.0.lot_cd", "source": "input", "type": "str"}
                    ]
                }
            ],
        }
    ],
}


def test_approvals_are_given_and_offers_declined():
    for waiting, value in [
        (PLAN, {"action": "approve", "index": 0}),
        ({"type": "code_approval"}, {"approve": True}),
        ({"type": "memory_change"}, {"approve": False}),
        ({"type": "workflow_save"}, {"approve": False}),
    ]:
        assert auto_replies.reply(waiting) == value
        assert hitl.validate(waiting, value) == []  # what create_run checks


def test_questions_and_missing_plan_values_go_to_the_user():
    question = {"type": "question", "question": "어느 lot?", "options": ["A"]}
    assert auto_replies.reply(question) is None
    assert auto_replies.ask(question) == "어느 lot?\n- A"
    empty = json.loads(json.dumps(PLAN))
    empty["candidates"][0]["input_values"] = {}
    assert auto_replies.reply(empty) is None
    assert "0.0.lot_cd" in auto_replies.ask(empty)


def test_transcript_streams_and_appends_an_unstreamed_answer():
    sent: list[str] = []
    transcript = Transcript(sent.append)
    transcript.add("계획을 세웠습니다.")
    transcript.paragraph()
    transcript.add("분석 결과")
    assert transcript.finish("분석 결과") == "계획을 세웠습니다.\n\n분석 결과"
    assert transcript.finish("다른 답") == (
        "계획을 세웠습니다.\n\n분석 결과\n\n다른 답"
    )
    assert "".join(sent) == transcript.text


def _follow(sent: list[str]) -> _Follow:
    services = SimpleNamespace(
        settings=SimpleNamespace(public_api_origin="https://svc/")
    )
    follow = _Follow(services, None, "s1", Transcript(sent.append))  # type: ignore[arg-type]
    follow.run_id = "r1"
    return follow


async def test_follow_turns_events_into_the_answer():
    sent: list[str] = []
    follow = _follow(sent)
    events = [
        {"type": "token", "run_id": "other", "data": {"text": "x"}},
        {"type": "token", "run_id": "r1", "data": {"text": "안녕"}},
        {"id": 5, "type": "tool_call", "run_id": "r1", "data": {}},
        {"id": 5, "type": "tool_call", "run_id": "r1", "data": {}},
        {
            "id": 6,
            "type": "artifact",
            "run_id": "r1",
            "data": {"kind": "report", "artifact_id": "a1", "title": "리포트"},
        },
        {
            "id": 7,
            "type": "message_final",
            "run_id": "r1",
            "data": {"content": "끝"},
        },
    ]
    for event in events:
        assert await follow.handle(event) is None
    done = await follow.handle(
        {
            "id": 8,
            "type": "run_status",
            "run_id": "r1",
            "data": {"status": "succeeded"},
        }
    )
    assert done is not None
    assert done.answer == "안녕\n\n끝"
    assert done.urls == [
        {"name": "리포트", "url": "https://svc/view/artifacts/a1"}
    ]
    assert "".join(sent) == done.answer


async def test_follow_asks_once_per_question():
    follow = _follow([])
    question = {"type": "question", "interrupt_id": "q1", "question": "몇 개?"}
    done = await follow.on_pause(question)
    assert done is not None and done.answer == "몇 개?"
    assert await follow.on_pause(question) is None


async def test_graph_answers_without_services_and_input():
    runtime.set_services(None)
    app = graph.build_graph()
    out = await app.ainvoke({"query": "hi", "user_id": "e1", "trace_id": "t"})
    assert out["answer"].startswith("분석 서비스가 준비 중")
    assert out["trace_id"] == "t" and out["docs"] == [] and out["urls"] == []
    runtime.set_services(SimpleNamespace())  # type: ignore[arg-type]
    try:
        out = await app.ainvoke({"query": "hi"})
        assert "user_id" in out["answer"]
    finally:
        runtime.set_services(None)


async def test_graph_streams_turn_text_as_custom_chunks(monkeypatch):
    async def fake_turn(services, *, write, **kwargs):
        write("부분 ")
        write("답")
        return SimpleNamespace(
            answer="부분 답", urls=[{"name": "n", "url": "u"}]
        )

    monkeypatch.setattr(graph, "run_turn", fake_turn)
    runtime.set_services(SimpleNamespace())  # type: ignore[arg-type]
    try:
        app = graph.build_graph()
        chunks = [
            chunk
            async for chunk in app.astream(
                {"query": "q", "user_id": "e1", "session_id": "g1"},
                stream_mode=["updates", "custom"],
            )
        ]
    finally:
        runtime.set_services(None)
    assert [c for mode, c in chunks if mode == "custom"] == ["부분 ", "답"]
    update = next(c for mode, c in chunks if mode == "updates")["answer"]
    assert update["answer"] == "부분 답" and update["urls"][0]["url"] == "u"


def test_workflow_module_exports_a_graph():
    from src.workflows.dtest import analyst

    assert hasattr(analyst.graph, "astream")


def test_gaia_sessions_table_is_registered():
    assert "gaia_sessions" in Base.metadata.tables


@pytest.fixture(autouse=True)
def _no_leftover_services():
    yield
    assert runtime.current() is None
