from core.workflows import spec


def test_examples_are_valid(adaptive, static, skills, tools):
    assert spec.validate(adaptive, skills, tools) == []
    assert spec.validate(static, skills, tools) == []


def test_execution_mode_is_derived(adaptive):
    adaptive["workflow"]["execution_mode"] = "static"
    assert spec.normalize(adaptive)["workflow"]["execution_mode"] == "adaptive"


def test_execution_must_follow_skill_rule(adaptive, skills, tools):
    adaptive["workflow"]["steps"][2]["tools"][1]["execution"] = "always"
    errors = spec.validate(adaptive, skills, tools)
    assert any("must be 'conditional'" in e for e in errors)


def test_unknown_output_and_forward_reference(adaptive, skills, tools):
    args = adaptive["workflow"]["steps"][1]["tools"][0]["arguments"]
    args["left_data"]["output"] = "nope"
    args["right_data"].update(step_index=2, tool_index=0)
    errors = spec.validate(adaptive, skills, tools)
    assert any("has no output 'nope'" in e for e in errors)
    assert any("earlier call" in e for e in errors)


def test_always_call_cannot_depend_on_conditional(adaptive, skills, tools):
    steps = adaptive["workflow"]["steps"]
    steps[2]["tools"].append(
        {"tool": "histogram_eda", "execution": "always", "arguments": {"data": {"source": "tool_output", "step_index": 2, "tool_index": 1, "output": "plot_path"}}}
    )
    assert any("cannot depend on conditional" in e for e in spec.validate(adaptive, skills, tools))


def test_input_slots(adaptive, tools):
    keys = [s["key"] for s in spec.input_slots(adaptive, tools)]
    assert "1.0.join_columns" in keys and "0.2.data_type" in keys
