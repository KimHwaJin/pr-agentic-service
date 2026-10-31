from src.dtest.agent.tool_labels import LABELS, tool_label


def test_labels():
    assert tool_label("read_skill", {"name": "eda"}) == "분석 skill 확인 · eda"
    assert tool_label("read_tool", {"names": ["a", "b"]}) == "도구 확인 · a, b"
    assert (
        tool_label("run_plan", {"decisions": [1]})
        == "조건 판단 후 이어서 실행"
    )
    assert tool_label("run_plan", {}) == "코드 실행 요청"
    assert tool_label("save_memory", {}) == "메모리 저장"  # no dangling ·
    assert tool_label("unknown_tool", {"x": 1}) == "unknown_tool"


def test_every_agent_tool_has_a_label():
    from src.dtest.agent.tools import analysis, batch, main

    names = {
        t.name
        for module in (analysis, batch, main)
        for t in vars(module).values()
        if hasattr(t, "name") and hasattr(t, "ainvoke")
    }
    assert names - set(LABELS) == set(), names - set(LABELS)
