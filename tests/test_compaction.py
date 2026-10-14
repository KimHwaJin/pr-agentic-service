import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.compaction import Rule, ToolResultCompactionMiddleware
from agent.compaction_rules import (
    execution_brief,
    finished_analysis,
    report_brief,
)


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
        _call("note", "n"),
        _result("짧은 결과", "n"),
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
        rules={"read_skill": Rule(result="clear")},
        **kwargs,
    )


def test_running_segment_is_untouched():
    assert _middleware().compact(_analysis(end=False)) == []


def test_finished_segment_is_rewritten_under_the_same_ids():
    changed = _middleware().compact(_analysis())
    assert [m.id for m in changed] == ["tm-r"]
    assert changed[0].content == "[compacted: read_skill]"
    assert changed[0].tool_call_id == "r"


def test_compaction_runs_once():
    messages = _analysis()
    changed = {m.id: m for m in _middleware().compact(messages)}
    messages = [changed.get(m.id, m) for m in messages]
    assert _middleware().compact(messages) == []


def test_messages_outside_segments_are_kept():
    messages = [
        _call("read_skill", "before"),
        _result("outside " * 50, "before"),
        *_analysis(),
    ]
    assert [m.id for m in _middleware().compact(messages)] == ["tm-r"]


def test_without_start_tools_each_end_closes_what_came_before():
    middleware = ToolResultCompactionMiddleware(
        end_tools={"finish_analysis"}, default=Rule(result=10)
    )
    changed = middleware.compact(_analysis())
    assert [m.id for m in changed] == ["tm-r"]  # the only one over 10


def test_argument_rules():
    middleware = ToolResultCompactionMiddleware(
        end_tools={"finish_analysis"},
        rules={"read_skill": Rule(args="clear")},
    )
    (changed,) = middleware.compact(_analysis())
    assert isinstance(changed, AIMessage)
    assert changed.tool_calls[0]["args"] == {"name": "[compacted: read_skill]"}
    assert changed.tool_calls[0]["id"] == "r"


def test_execution_brief_keeps_status_variables_and_errors():
    body = {
        "results": {
            "#0 extract_data": {
                "status": "SUCCEEDED",
                "observations": [
                    {
                        "var": "_r0",
                        "value": {"type": "DataFrame", "shape": [9, 3]},
                    }
                ],
                "stdout": "x" * 1000,
            },
            "#1 boxplot": {
                "status": "FAILED",
                "observations": [],
                "error": "KeyError: 'a'\nTraceback ...",
            },
        },
        "operation_error": None,
    }
    brief = execution_brief(json.dumps(body))
    assert "#0 extract_data: SUCCEEDED (_r0(DataFrame [9, 3]))" in brief
    assert "#1 boxplot: FAILED 오류: KeyError: 'a'" in brief
    assert "x" * 50 not in brief


def test_report_brief_keeps_summary_and_results():
    content = (
        "리포트 게시 완료 (report=a, notebook=b).\n\n# 제목\n\n"
        "## 1. 요약\n상관 0.33\n\n## 2. 수행한 분석\n긴 설명\n\n"
        "## 3. 주요 결과\nSN OPEN 0.3256\n\n## 6. 한계\n샘플"
    )
    brief = report_brief(content)
    assert brief.startswith("리포트 게시 완료 (report=a, notebook=b).")
    assert "상관 0.33" in brief and "SN OPEN 0.3256" in brief
    assert "긴 설명" not in brief and "샘플" not in brief


def test_end_tool_update_carries_the_compacted_segment():
    import asyncio
    from types import SimpleNamespace

    from langgraph.types import Command

    messages = _analysis()
    *state, end = messages
    request = SimpleNamespace(
        tool_call={"name": "finish_analysis", "id": "f", "args": {}},
        state={"messages": state},
    )

    async def handler(_):
        return Command(update={"messages": [end], "active_agent": "main"})

    result = asyncio.run(_middleware().awrap_tool_call(request, handler))
    assert result.update["active_agent"] == "main"
    assert [m.id for m in result.update["messages"]] == ["tm-f", "tm-r"]


def test_latest_only_keeps_the_last_copy_of_a_repeated_read():
    middleware = ToolResultCompactionMiddleware(
        start_tools={"start_analysis"},
        end_tools={"finish_analysis"},
        rules={"read_skill": Rule(latest_only=True)},
    )
    first = _analysis()
    again = [
        _call("start_analysis", "s2"),
        _result("넘김", "s2"),
        _call("read_skill", "r2", {"name": "data_load"}),
        _result("skill 문서 " * 200, "r2"),
        _call("read_skill", "r3", {"name": "eda"}),
        _result("다른 문서", "r3"),
    ]
    # second analysis still running: its copy wins, the first is cleared
    (changed,) = middleware.compact([*first, *again])
    assert changed.id == "tm-r"
    assert changed.content == "[compacted: read_skill, repeated later]"
    # a document read once stays
    assert middleware.compact(first) == []


def test_service_rules_assemble():
    assert finished_analysis().end_tools == {"finish_analysis"}
