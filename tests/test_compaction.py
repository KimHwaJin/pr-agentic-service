import asyncio
from types import SimpleNamespace

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    RemoveMessage,
    ToolMessage,
)
from langgraph.types import Command

from agent.compaction import KEEP, REMOVE, Rule, ToolResultCompactionMiddleware
from agent.compaction_rules import analysis_note, finished_analysis


def _call(name, call_id, args=None, msg_id=None):
    return AIMessage(
        "",
        id=msg_id or f"ai-{call_id}",
        tool_calls=[{"name": name, "args": args or {}, "id": call_id}],
    )


def _result(content, call_id):
    return ToolMessage(content, tool_call_id=call_id, id=f"tm-{call_id}")


def _analysis(end=True):
    messages = [
        HumanMessage("분석해줘", id="h1"),
        _call("start_analysis", "s", {"task": "기술통계"}),
        _result("분석 담당에게 넘김", "s"),
        _call("read_skill", "r", {"name": "data_load"}),
        _result("skill 문서 " * 200, "r"),
        _call("write_report", "w", {"title": "t"}),
        _result("리포트 게시 완료 (report=a, notebook=b).\n\n본문", "w"),
    ]
    if end:
        messages += [
            _call("finish_analysis", "f", {"summary": "평균 3.2"}),
            _result("분석 종료. 요약:\n평균 3.2", "f"),
        ]
    return messages


def _middleware(**kwargs):
    return ToolResultCompactionMiddleware(
        start_tools={"start_analysis"},
        end_tools={"finish_analysis"},
        rules={"start_analysis": KEEP, "finish_analysis": KEEP},
        default=REMOVE,
        **kwargs,
    )


def _removed(changed):
    return {m.id for m in changed if isinstance(m, RemoveMessage)}


def test_running_segment_is_untouched():
    assert _middleware().compact(_analysis(end=False)) == []


def test_finished_segment_drops_calls_and_results():
    changed = _middleware().compact(_analysis())
    assert _removed(changed) == {"ai-r", "tm-r", "ai-w", "tm-w"}


def test_messages_outside_segments_are_kept():
    messages = [
        _call("read_skill", "before"),
        _result("outside", "before"),
        *_analysis(),
    ]
    assert "tm-before" not in _removed(_middleware().compact(messages))


def test_mixed_calls_keep_the_kept_call():
    both = AIMessage(
        "",
        id="ai-both",
        tool_calls=[
            {"name": "read_skill", "args": {}, "id": "x"},
            {"name": "finish_analysis", "args": {}, "id": "f"},
        ],
    )
    messages = [
        _call("start_analysis", "s"),
        _result("넘김", "s"),
        both,
        _result("doc", "x"),
        _result("분석 종료", "f"),
    ]
    changed = {m.id: m for m in _middleware().compact(messages)}
    assert isinstance(changed["tm-x"], RemoveMessage)
    kept = changed["ai-both"]
    assert isinstance(kept, AIMessage)
    assert [c["id"] for c in kept.tool_calls] == ["f"]


def test_result_rules_rewrite_under_the_same_id():
    middleware = ToolResultCompactionMiddleware(
        end_tools={"finish_analysis"},
        rules={"read_skill": Rule(result="clear")},
    )
    (changed,) = middleware.compact(_analysis())
    assert (
        changed.id == "tm-r" and changed.content == "[compacted: read_skill]"
    )
    assert (
        middleware.compact(
            [changed if m.id == "tm-r" else m for m in _analysis()]
        )
        == []
    )


def test_end_tool_update_carries_note_and_removals():
    *state, end = _analysis()
    request = SimpleNamespace(
        tool_call={"name": "finish_analysis", "id": "f", "args": {}},
        state={"messages": state},
    )

    async def handler(_):
        return Command(update={"messages": [end], "active_agent": "main"})

    middleware = _middleware(note=analysis_note)
    result = asyncio.run(middleware.awrap_tool_call(request, handler))
    assert result.update["active_agent"] == "main"
    first, *rest = result.update["messages"]
    assert first.id == "tm-f"
    assert "report=a, notebook=b" in first.content
    assert _removed(rest) == {"ai-r", "tm-r", "ai-w", "tm-w"}


def test_other_tools_pass_through():
    request = SimpleNamespace(
        tool_call={"name": "read_skill", "id": "r", "args": {}},
        state={"messages": _analysis(end=False)},
    )

    async def handler(_):
        return "doc"

    assert (
        asyncio.run(_middleware().awrap_tool_call(request, handler)) == "doc"
    )


def test_service_rules_assemble():
    assert finished_analysis().end_tools == {"finish_analysis"}
