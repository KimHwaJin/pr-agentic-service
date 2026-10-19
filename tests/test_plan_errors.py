"""Validation errors tell the model how to fix the plan."""

from types import SimpleNamespace

from agent import plan_format
from agent.graph import tool_error
from agent.tools.analysis import _plan_help, _referenced
from core.workflows import spec


def _validate(calls, skills, tools):
    document, _ = plan_format.to_workflow(
        calls, name="t", user_request="q", skills=skills
    )
    return spec.validate(document, skills, tools)


def test_wrong_parameter_gets_the_real_signature(skills, tools):
    errors = _validate(
        [
            {
                "skill": "data_load",
                "tool": "extract_data",
                "args": {"data_type": "nce", "lots": "L1"},
            }
        ],
        skills,
        tools,
    )
    found = _referenced(errors)
    assert found["tools"] == {"extract_data"}
    help_text = _plan_help(found, skills, tools)
    assert "### extract_data (skill `data_load`)" in help_text
    assert tools.describe("extract_data") in help_text


def test_unknown_tool_and_skill_list_what_exists(skills, tools):
    errors = _validate(
        [{"skill": "data_loader", "tool": "extract", "args": {}}],
        skills,
        tools,
    )
    help_text = _plan_help(_referenced(errors), skills, tools)
    assert "### extract\n없는 tool입니다. 비슷한 tool:" in help_text
    assert "extract_data" in help_text
    assert "### skill data_loader\n없는 skill입니다." in help_text


def test_missing_required_parameter_names_the_tool(skills, tools):
    errors = _validate(
        [{"skill": "eda_analysis", "tool": "compute_statistics", "args": {}}],
        skills,
        tools,
    )
    assert any(
        "'compute_statistics' is missing required parameter" in e
        for e in errors
    )
    assert _referenced(errors)["tools"] == {"compute_statistics"}


def test_valid_plan_needs_no_help(skills, tools):
    assert _plan_help(_referenced([]), skills, tools) == ""


def test_argument_mismatch_lists_the_tool_arguments():
    request = SimpleNamespace(
        tool=SimpleNamespace(args={"call": {}, "new_args": {}})
    )
    exc = TypeError(
        "revise_call() got an unexpected keyword argument 'v__args'"
    )
    message = tool_error(exc, request)
    assert message.endswith("이 도구의 인자: call, new_args")
