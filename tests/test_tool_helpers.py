"""Tool files with helpers, and shared helpers under ``_lib``.

The cell holds only definitions (imports, functions, classes, assignments)
without any docstring; ``from _lib.<module> import name`` is replaced by the
helpers the tool uses.
"""

import textwrap
from pathlib import Path

from src.dtest.agent.codegen import tool_step_code
from src.dtest.core.assets import ToolCatalog
from src.dtest.core.workflows.spec import Call


def _write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).lstrip(), "utf-8")


def _run(tool, **kwargs):
    namespace: dict = {}
    exec(compile(tool.code, tool.name, "exec"), namespace)
    return namespace[tool.name](**kwargs), namespace


TOOL = '''
"""Module docstring: not sent."""

import math

# a comment between definitions: not sent
SCALE = 2
"a note left in the file: not sent"


def _double(x):
    """Helper docstring: not sent."""
    # kept: a comment inside a function
    return x * SCALE


class _Box:
    """Class docstring: not sent."""

    def size(self):
        """Method docstring: not sent."""


def scaled(x: float) -> dict:
    """Main docstring: kept for the model only.

    Args:
        x: input
    """

    def inner(v):
        """Nested docstring: not sent."""
        return math.floor(v)

    return {"value": inner(_double(x)), "box": _Box().size()}


if __name__ == "__main__":
    print(scaled(1.5))
'''


def test_cell_holds_definitions_without_docstrings(tmp_path):
    _write(tmp_path, "eda/scaled.py", TOOL)
    catalog = ToolCatalog.load(tmp_path)
    tool = catalog.tools["scaled"]
    code = tool.code
    assert "docstring" not in code and '"""' not in code
    assert "not sent" not in code  # notes, comments outside functions
    assert "__main__" not in code and "print(" not in code
    assert "# kept: a comment inside a function" in code
    assert code.startswith("import math\n\nSCALE = 2\n\n\ndef _double(x):")
    assert "    def size(self):\n        pass" in code
    # the model still sees the main docstring and its outputs
    assert tool.docstring.startswith("Main docstring")
    assert tool.param_docs == {"x": "input"}
    assert tool.outputs == ("value", "box")
    result, namespace = _run(tool, x=1.6)
    assert result == {"value": 3, "box": None}
    assert {n for n, _ in tool.names} == {"SCALE", "_double", "_Box"}


def test_single_function_tool_is_sent_as_before(tmp_path):
    _write(
        tmp_path,
        "eda/plain.py",
        '''
        def plain(x):
            """Only a docstring."""
            import json

            return {"y": json.dumps(x)}
        ''',
    )
    tool = ToolCatalog.load(tmp_path).tools["plain"]
    assert tool.code == (
        "def plain(x):\n    import json\n\n    return {'y': json.dumps(x)}"
    ).replace("'y'", '"y"')
    assert tool.names == ()


def test_top_level_code_that_runs_breaks_the_tool(tmp_path):
    _write(
        tmp_path,
        "eda/noisy.py",
        """
        import warnings

        warnings.filterwarnings("ignore")


        def noisy(x):
            return x
        """,
    )
    _write(
        tmp_path,
        "eda/looping.py",
        """
        for i in range(3):
            pass


        def looping(x):
            return x
        """,
    )
    catalog = ToolCatalog.load(tmp_path)
    assert not catalog.tools
    assert "3행" in catalog.broken["noisy"]
    assert "변수 대입만" in catalog.broken["looping"]


def test_docstring_on_the_def_line_is_reported(tmp_path):
    _write(tmp_path, "eda/short.py", 'def short(x): "doc"; return x\n')
    catalog = ToolCatalog.load(tmp_path)
    assert "docstring은 줄을 따로" in catalog.broken["short"]


def test_computed_constant_is_kept_with_a_warning(tmp_path):
    _write(
        tmp_path,
        "eda/heavy.py",
        """
        _TABLE = dict(a=1)


        def heavy(k):
            return _TABLE[k]
        """,
    )
    catalog = ToolCatalog.load(tmp_path)
    assert _run(catalog.tools["heavy"], k="a")[0] == 1
    [warnings] = catalog.warnings.values()
    assert "함수 호출" in warnings[0]


LIB_STATS = '''
"""Shared statistics helpers."""

import math
import statistics as st

from _lib.fmt import label

_DIGITS = 3


def _round(v):
    """Not sent."""
    return round(v, _DIGITS)


def spread(values):
    """Not sent either."""
    return _round(st.pstdev(values))


def summary(values):
    return {"mean": _round(st.mean(values)), "sd": spread(values)}


def unused(values):
    return math.fsum(values)


def described(values):
    return label("n", len(values))
'''

LIB_FMT = """
def label(name, value):
    return f"{name}={value}"


def unrelated():
    return 0
"""


def _with_lib(root: Path) -> None:
    _write(root, "_lib/stats.py", LIB_STATS)
    _write(root, "_lib/fmt.py", LIB_FMT)


def test_lib_helpers_are_cut_to_what_the_tool_uses(tmp_path):
    _with_lib(tmp_path)
    _write(
        tmp_path,
        "stats/describe_values.py",
        '''
        from _lib.stats import described, summary


        def describe_values(values: list) -> dict:
            """Summary of a list."""
            return {"summary": summary(values), "label": described(values)}
        ''',
    )
    catalog = ToolCatalog.load(tmp_path)
    assert set(catalog.tools) == {"describe_values"}  # _lib is not a tool
    code = catalog.tools["describe_values"].code
    assert "from _lib" not in code
    assert "def unused" not in code and "import math" not in code
    assert "def unrelated" not in code
    assert '"""' not in code and "Not sent" not in code
    # dependencies first: fmt, then stats, then the tool
    assert (
        code.index("# --- _lib/fmt.py ---")
        < code.index("# --- _lib/stats.py ---")
        < code.index("# --- describe_values.py ---")
    )
    result, _ = _run(catalog.tools["describe_values"], values=[1, 2, 3, 4])
    assert result == {
        "summary": {"mean": 2.5, "sd": 1.118},
        "label": "n=4",
    }


def test_helper_change_changes_the_tool_code(tmp_path):
    _with_lib(tmp_path)
    _write(
        tmp_path,
        "stats/sd.py",
        """
        from _lib.stats import spread


        def sd(values):
            return {"sd": spread(values)}
        """,
    )
    before = ToolCatalog.load(tmp_path).tools["sd"].code
    _write(
        tmp_path,
        "_lib/stats.py",
        LIB_STATS.replace("_DIGITS = 3", "_DIGITS = 1"),
    )
    after = ToolCatalog.load(tmp_path).tools["sd"].code
    assert before != after  # so tool_version (its sha256) changes too


def test_bad_lib_imports_break_the_tool(tmp_path):
    _with_lib(tmp_path)
    _write(
        tmp_path,
        "_lib/a.py",
        "from _lib.b import g\n\ndef f():\n    return g()\n",
    )
    _write(
        tmp_path,
        "_lib/b.py",
        "from _lib.a import f\n\ndef g():\n    return f()\n",
    )
    cases = {
        "missing_name": "from _lib.stats import nothing",
        "missing_module": "from _lib.nowhere import x",
        "aliased": "from _lib.stats import spread as s",
        "whole": "import _lib.stats",
        "cycle": "from _lib.a import f",
    }
    _write(
        tmp_path,
        "t/nested.py",
        "def nested():\n"
        "    from _lib.stats import spread\n\n"
        "    return spread\n",
    )
    for name, line in cases.items():
        _write(
            tmp_path,
            f"t/{name}.py",
            f"{line}\n\n\ndef {name}():\n    return 1\n",
        )
    broken = ToolCatalog.load(tmp_path).broken
    assert "nothing" in broken["missing_name"]
    assert "nowhere" in broken["missing_module"]
    assert "별칭" in broken["aliased"]
    assert "from _lib.<모듈>" in broken["whole"]
    assert "서로를 가져옵니다" in broken["cycle"]
    assert "최상위에서 가져옵니다" in broken["nested"]


def test_kernel_name_clashes_break_the_tools(tmp_path):
    _with_lib(tmp_path)
    shared = "from _lib.stats import spread\n\n\n"
    _write(
        tmp_path, "a/one.py", shared + "def one(v):\n    return spread(v)\n"
    )
    _write(
        tmp_path, "a/two.py", shared + "def two(v):\n    return spread(v)\n"
    )
    helper = "def _fix(v):\n    return v{}\n\n\n"
    _write(
        tmp_path,
        "b/three.py",
        helper.format("") + "def three(v):\n    return _fix(v)\n",
    )
    _write(
        tmp_path,
        "b/four.py",
        helper.format(" + 1") + "def four(v):\n    return _fix(v)\n",
    )
    _write(
        tmp_path,
        "c/five.py",
        "def one(v):\n    return v\n\n\ndef five(v):\n    return v\n",
    )
    _write(
        tmp_path,
        "c/six.py",
        "_agentic_observe = None\n\n\ndef six(v):\n    return v\n",
    )
    catalog = ToolCatalog.load(tmp_path)
    # the same _lib helper in two tools is the same code: no clash
    assert {"one", "two"} <= set(catalog.tools)
    assert (
        "four" in catalog.broken["three"] and "three" in catalog.broken["four"]
    )
    assert "다른 tool 이름" in catalog.broken["five"]
    assert "생성 코드" in catalog.broken["six"]


def test_later_root_replaces_a_lib_module(tmp_path):
    base, ext = tmp_path / "base", tmp_path / "ext"
    _write(base, "_lib/num.py", "def k():\n    return 1\n")
    _write(ext, "_lib/num.py", "def k():\n    return 2\n")
    _write(
        base,
        "t/value.py",
        "from _lib.num import k\n\n\ndef value():\n    return k()\n",
    )
    catalog = ToolCatalog.load_many([base, ext])
    assert _run(catalog.tools["value"])[0] == 2


def test_step_code_runs_a_tool_with_helpers(tmp_path):
    _with_lib(tmp_path)
    _write(tmp_path, "eda/scaled.py", TOOL)
    _write(
        tmp_path,
        "stats/sd.py",
        """
        from _lib.stats import spread


        def sd(values):
            return {"sd": spread(values)}
        """,
    )
    catalog = ToolCatalog.load(tmp_path)
    seen = {}
    namespace = {
        "_agentic_observe": lambda name, value: seen.update({name: value})
    }
    for index, (tool, args) in enumerate(
        [("scaled", {"x": 2}), ("sd", {"values": [1, 3]})]
    ):
        call = Call(
            0,
            index,
            "s",
            tool,
            "always",
            {k: {"source": "literal", "value": v} for k, v in args.items()},
        )
        exec(tool_step_code(call, {}, catalog, {}), namespace)
    assert seen == {
        "_r_s0_t0": {"value": 4, "box": None},
        "_r_s0_t1": {"sd": 1.0},
    }
