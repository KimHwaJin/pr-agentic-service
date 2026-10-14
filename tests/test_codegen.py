from agent.codegen import parse_observations, tool_step_code
from core.workflows import spec


def test_tool_step_code(adaptive, tools):
    calls = {c.key: c for c in spec.calls(adaptive)}
    producers = {k: c.tool for k, c in calls.items()}
    values = {"1.0.join_columns": ["alias_lot_id", "wf_id"]}
    code = tool_step_code(calls["1.0"], values, tools, producers)
    compile(code, "step", "exec")
    assert (
        "_r_s1_t0 = merge_data(left_data=_r_s0_t1['data'], "
        "right_data=_r_s0_t3['data'], "
        "join_columns=['alias_lot_id', 'wf_id'], how='inner')" in code
    )
    assert '"""' not in code  # docstring stripped
    assert "def _agentic_observe" not in code  # defined once, in SETUP


def test_setup_defines_the_observation_helper():
    from agent.codegen import SETUP

    namespace: dict = {"get_ipython": lambda: None}
    exec(compile(SETUP, "setup", "exec"), namespace)
    assert callable(namespace["_agentic_observe"])


def test_empty_optional_inputs_use_tool_defaults(adaptive, tools):
    calls = {c.key: c for c in spec.calls(adaptive)}
    code = tool_step_code(calls["0.0"], {"0.0.data_type": "nce"}, tools, {})
    assert "_r_s0_t0 = extract_data(data_type='nce')" in code


def test_parse_observations():
    obs, rest = parse_observations(
        'hello\nAGENTIC_OBSERVATION {"var": "x", "value": 1}\nbye'
    )
    assert obs == [{"var": "x", "value": 1}] and rest == "hello\nbye"


def test_json_string_arguments_are_decoded():
    from agent.middleware.json_arguments import _structured

    assert _structured({"type": "array"}) and _structured(
        {"anyOf": [{"type": "object"}, {"type": "null"}]}
    )
    assert not _structured({"type": "string"})


def test_observation_summarises_plain_objects(capsys):
    import json

    from agent.codegen import SETUP

    namespace: dict = {"get_ipython": lambda: None}
    exec(compile(SETUP, "setup", "exec"), namespace)

    class Model:
        def __init__(self):
            self.coef_ = [1.5, 2.0]
            self.fitted = None
            self._private = 1

    namespace["_agentic_observe"]("m", Model())
    namespace["_agentic_observe"]("d", {"a": {"b": {"c": 1}}})
    out = capsys.readouterr().out.splitlines()
    model, nested = (json.loads(line.split(" ", 1)[1]) for line in out)
    assert model["value"]["attrs"] == {"coef_": "[1.5, 2.0]"}
    assert nested["value"] == {"a": {"b": "{'c': 1}"}}
