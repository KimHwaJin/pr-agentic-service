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


def test_compact_plan_to_workflow(skills, tools):
    from agent import plan_format

    calls = [
        {"skill": "data_load", "tool": "extract_data", "args": {"data_type": "$input"}},
        {"skill": "data_load", "tool": "transform_nce", "args": {"data": "@0.data"}},
        {"skill": "dataset_preparation", "tool": "sample_data", "args": {"data": "@1.data", "sample_size": 1000}},
        {"skill": "eda_analysis", "tool": "compute_statistics", "args": {"data": "@2.sampled_data"}},
        {"skill": "eda_analysis", "tool": "boxplot_eda", "execution": "always", "args": {"data": "@2.sampled_data"}},
    ]
    document, keys = plan_format.to_workflow(calls, name="t", user_request="r", skills=skills)
    assert keys == ["0.0", "0.1", "1.0", "2.0", "2.1"]
    assert document["workflow"]["steps"][2]["tools"][1]["execution"] == "conditional"  # from the skill rule
    assert spec.validate(document, skills, tools) == []
    assert plan_format.input_keys({"0.data_type": "nce"}, keys) == {"0.0.data_type": "nce"}
    assert plan_format.describe(document)[1]["args"] == {"data": "@0.data"}
