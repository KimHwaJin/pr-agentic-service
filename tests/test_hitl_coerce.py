"""Plan approval values typed as text take the parameter's type."""

import copy

from test_runs_api import PLAN_FULL

from api_service.services import hitl


def _approve(input_values=None, overrides=None):
    return {
        "action": "approve",
        "index": 0,
        "input_values": input_values or {},
        "overrides": overrides or {},
    }


def test_text_becomes_the_parameter_type():
    value = hitl.coerce(
        PLAN_FULL, _approve({"0.0.lot_cd": "123"}, {"1.0.n": "500"})
    )
    assert value["input_values"]["0.0.lot_cd"] == "123"  # str stays text
    assert value["overrides"]["1.0.n"] == 500
    assert hitl.validate(PLAN_FULL, value) == []


def test_empty_text_is_null_where_null_is_allowed():
    value = hitl.coerce(PLAN_FULL, _approve(overrides={"1.0.k": " "}))
    assert value["overrides"]["1.0.k"] is None


def test_text_that_does_not_fit_is_left_for_the_type_check():
    value = hitl.coerce(PLAN_FULL, _approve(overrides={"1.0.n": "abc"}))
    assert value["overrides"]["1.0.n"] == "abc"
    assert hitl.validate(PLAN_FULL, value)  # 422 names the expected type


def test_unknown_types_and_other_questions_are_untouched():
    value = hitl.coerce(PLAN_FULL, _approve(overrides={"1.0.any": "[1]"}))
    assert value["overrides"]["1.0.any"] == "[1]"
    question = {"type": "question"}
    reply = {"answer": "500"}
    assert hitl.coerce(question, copy.deepcopy(reply)) == reply
