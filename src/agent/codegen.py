"""Deterministic code assembly.

One tool call = function source (no docstring) + call + observation.
Every new execution starts with one SETUP cell that defines the
observation helper, so tool cells carry only the tool and its call.
"""

import json
from typing import Any

from core.assets import ToolCatalog
from core.workflows.spec import Call

OBSERVATION_PREFIX = "AGENTIC_OBSERVATION "
SETUP_TOOL = "setup"

SETUP = """
# 에이전트 준비 셀: 그림을 노트북에 표시하고, 각 단계 결과를 에이전트가
# 읽을 수 있게 요약해 출력하는 _agentic_observe 함수를 정의합니다.
try:  # render figures as notebook outputs
    get_ipython().run_line_magic("matplotlib", "inline")
except Exception:
    pass


def _agentic_observe(name, value):
    import json

    def num(x):
        x = x.item() if hasattr(x, "item") else x
        if isinstance(x, bool | int | str) or x is None:
            return x
        try:
            return round(float(x), 6)
        except (TypeError, ValueError):
            return str(x)

    def frame(v):
        # compact: rows and stats are lists aligned with "columns"
        cols = v.columns[:30]
        kinds = v.dtypes.value_counts()
        out = {
            "type": "DataFrame",
            "shape": list(v.shape),
            "columns": [str(c) for c in cols],
            "dtypes": {str(t): int(n) for t, n in kinds.items()},
            "head": [[num(x) for x in row] for row in v[cols].head(3).values],
        }
        numeric = [c for c in cols if v[c].dtype.kind in "biuf"]
        if numeric:
            stats = v[numeric].describe().loc[["mean", "std", "min", "max"]]
            out["describe"] = {
                "fields": ["mean", "std", "min", "max"],
                **{str(c): [num(x) for x in stats[c]] for c in numeric},
            }
        return out

    def array(v):
        out = {"type": "ndarray", "shape": list(v.shape)}
        out["dtype"] = str(v.dtype)
        if v.size and v.dtype.kind in "biuf":
            out.update(min=num(v.min()), max=num(v.max()), mean=num(v.mean()))
        out["head"] = [num(x) for x in v.ravel()[:5]]
        return out

    def empty(x):
        return x is None or (isinstance(x, list | dict | tuple) and not x)

    def obj(v):
        kind = type(v)
        out = {"type": f"{kind.__module__}.{kind.__qualname__}"}
        if hasattr(v, "shape"):
            out["shape"] = str(getattr(v, "shape"))
        if kind.__name__ == "Figure" and hasattr(v, "axes"):  # matplotlib
            titles = [a.get_title() for a in v.axes]
            out["axes"] = len(titles)
            out["titles"] = [t for t in titles if t][:10]
            return out
        attrs = {
            k: repr(x)[:120]
            for k, x in list(getattr(v, "__dict__", {}).items())[:40]
            if not k.startswith("_")
            and not callable(x)
            and not empty(x)
        }
        if attrs:
            out["attrs"] = dict(list(attrs.items())[:10])
        out["repr"] = repr(v)[:200]
        return out

    def brief(v, depth=0):
        if v is None or isinstance(v, (bool, int, float, str)):
            text = repr(v)
            return text if len(text) <= 500 else text[:500] + "..."
        try:
            import pandas as pd
            if isinstance(v, pd.DataFrame):
                return frame(v)
            if isinstance(v, pd.Series):
                head = v.head(10).to_dict()
                return {"type": "Series", "len": len(v), "head": head}
        except ImportError:
            pass
        try:
            import numpy as np
            if isinstance(v, np.ndarray):
                return array(v)
            if isinstance(v, np.generic):
                return num(v)
        except ImportError:
            pass
        if isinstance(v, dict) and depth < 2:
            items = list(v.items())[:30]
            return {str(k): brief(x, depth + 1) for k, x in items}
        if isinstance(v, (list, tuple)) and depth < 2:
            head = [brief(x, depth + 1) for x in v[:5]]
            return {"type": type(v).__name__, "len": len(v), "head": head}
        if isinstance(v, (dict, list, tuple, set)):
            text = repr(v)
            return text if len(text) <= 500 else text[:500] + "..."
        return obj(v)

    try:
        summary = brief(value)
    except Exception as exc:  # never fail the step because of the summary
        summary = f"(요약 실패: {type(exc).__name__}) {repr(value)[:300]}"
    payload = {"var": name, "value": summary}
    dumped = json.dumps(payload, default=str, ensure_ascii=False)
    print("AGENTIC_OBSERVATION " + dumped)
""".strip()


def _literal(value: Any) -> str:
    # JSON value -> Python literal; the json round-trip + repr renders
    # None/True/False correctly
    return repr(json.loads(json.dumps(value)))


def tool_step_code(
    call: Call,
    input_values: dict[str, Any],
    tools: ToolCatalog,
    producers: dict[str, str],
) -> str:
    """Builds one tool call step.

    ``producers`` maps a call key to its tool name so single-value outputs
    are referenced whole.
    """
    tool = tools.tools[call.tool]
    args = []
    for name, arg in call.arguments.items():
        if arg["source"] == "literal":
            expr = _literal(arg["value"])
        elif arg["source"] == "input":
            key = f"{call.key}.{name}"
            if input_values.get(key) is None:
                # optional input left empty: the tool's default applies
                continue
            expr = _literal(input_values[key])
        else:
            ref = f"{arg['step_index']}.{arg['tool_index']}"
            var = f"_r_s{arg['step_index']}_t{arg['tool_index']}"
            expr = tools.tools[producers[ref]].output_expr(var, arg["output"])
        args.append(f"{name}={expr}")
    return (
        f"{tool.code}\n\n"
        f"{call.var} = {tool.name}({', '.join(args)})\n"
        f"_agentic_observe({call.var!r}, {call.var})\n"
    )


def setup_step(storage: Any, timeout: int | None) -> dict[str, Any]:
    """The first step of every new execution (kernel)."""
    return {
        "payload": {
            "type": "PYTHON_EXECUTE",
            "source": storage.write_source(SETUP + "\n"),
        },
        "step_timeout_seconds": timeout,
        "lineage": {"skill_name": "agentic", "tool_name": SETUP_TOOL},
    }


def custom_step_code(code: str, observe: list[str]) -> str:
    lines = [code.rstrip(), ""]
    lines += [f"_agentic_observe({name!r}, {name})" for name in observe]
    return "\n".join(lines) + "\n"


def parse_observations(text: str) -> tuple[list[dict[str, Any]], str]:
    """Splits stdout into structured observations and remaining text."""
    observations, rest = [], []
    for line in text.splitlines():
        if line.startswith(OBSERVATION_PREFIX):
            try:
                observations.append(
                    json.loads(line[len(OBSERVATION_PREFIX) :])
                )
                continue
            except ValueError:
                pass
        rest.append(line)
    return observations, "\n".join(rest)
