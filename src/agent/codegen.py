"""Deterministic code assembly: one tool call = function source (no docstring) + call + observation."""

import json
from typing import Any

from core.assets import ToolCatalog
from core.workflows.spec import Call

OBSERVATION_PREFIX = "AGENTIC_OBSERVATION "

OBSERVE = """
def _agentic_observe(name, value):
    import json

    def brief(v, depth=0):
        try:
            import pandas as pd
            if isinstance(v, pd.DataFrame):
                return {"type": "DataFrame", "shape": list(v.shape), "columns": [str(c) for c in v.columns[:50]],
                        "head": v.head(5).to_dict(orient="records")}
            if isinstance(v, pd.Series):
                return {"type": "Series", "len": len(v), "head": v.head(10).to_dict()}
        except ImportError:
            pass
        if isinstance(v, dict) and depth < 2:
            return {str(k): brief(x, depth + 1) for k, x in list(v.items())[:30]}
        if isinstance(v, (list, tuple)) and depth < 2:
            return {"type": type(v).__name__, "len": len(v), "head": [brief(x, depth + 1) for x in v[:5]]}
        text = repr(v)
        return text if len(text) <= 500 else text[:500] + "..."

    print("AGENTIC_OBSERVATION " + json.dumps({"var": name, "value": brief(value)}, default=str, ensure_ascii=False))
""".strip()


def _literal(value: Any) -> str:
    # JSON value -> Python literal (None/True/False come out right through json round-trip + repr)
    return repr(json.loads(json.dumps(value)))


def tool_step_code(call: Call, input_values: dict[str, Any], tools: ToolCatalog, producers: dict[str, str]) -> str:
    """``producers`` maps a call key to its tool name so single-value outputs are referenced whole."""
    tool = tools.tools[call.tool]
    args = []
    for name, arg in call.arguments.items():
        if arg["source"] == "literal":
            expr = _literal(arg["value"])
        elif arg["source"] == "input":
            key = f"{call.key}.{name}"
            if input_values.get(key) is None:
                continue  # optional input left empty: the tool's default applies
            expr = _literal(input_values[key])
        else:
            ref = f"{arg['step_index']}.{arg['tool_index']}"
            var = f"_r_s{arg['step_index']}_t{arg['tool_index']}"
            expr = tools.tools[producers[ref]].output_expr(var, arg["output"])
        args.append(f"{name}={expr}")
    return (
        f"{tool.code}\n\n{OBSERVE}\n\n"
        f"{call.var} = {tool.name}({', '.join(args)})\n"
        f"_agentic_observe({call.var!r}, {call.var})\n"
    )


def custom_step_code(code: str, observe: list[str]) -> str:
    lines = [code.rstrip(), "", OBSERVE, ""]
    lines += [f"_agentic_observe({name!r}, {name})" for name in observe]
    return "\n".join(lines) + "\n"


def parse_observations(text: str) -> tuple[list[dict[str, Any]], str]:
    """Splits stdout into structured observations and the remaining human text."""
    observations, rest = [], []
    for line in text.splitlines():
        if line.startswith(OBSERVATION_PREFIX):
            try:
                observations.append(json.loads(line[len(OBSERVATION_PREFIX) :]))
                continue
            except ValueError:
                pass
        rest.append(line)
    return observations, "\n".join(rest)
