from agent.tools.analysis import _segment
from core.workflows import spec


def _plan(document):
    return {"document": document, "calls": {c.key: {"status": "pending"} for c in spec.calls(document)}}


def test_segment_stops_before_undecided_conditional(adaptive):
    plan = _plan(adaptive)
    segment, undecided = _segment(plan, {})
    assert [c.key for c in segment] == ["0.0", "0.1", "0.2", "0.3", "1.0", "1.1", "2.0"]
    assert undecided == ["2.1", "2.2"]


def test_decisions_run_or_skip(adaptive):
    plan = _plan(adaptive)
    for key in ["0.0", "0.1", "0.2", "0.3", "1.0", "1.1", "2.0"]:
        plan["calls"][key]["status"] = "succeeded"
    segment, undecided = _segment(plan, {"2.1": {"run": False, "reason": "no outliers"}, "2.2": {"run": True}})
    assert [c.key for c in segment] == ["2.2"]
    assert plan["calls"]["2.1"]["status"] == "skipped" and undecided == []
