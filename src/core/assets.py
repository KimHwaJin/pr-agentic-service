"""Skill (.md) and Tool (.py) catalogs read from configurable directories.

Skills: ``<root>/<category>/<name>.md`` with ``name``/``description``
frontmatter. Analysis skills carry a ``## Tool list`` table
(Tool | 실행 방식 | 실행 조건 | condition_tool | 역할).
Tools: ``<root>/<category>/<tool>.py`` holding one top-level function named
like the file. Imports live inside the function; the executor receives the
function without its docstring.
"""

import ast
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.S)
_TABLE_ROW = re.compile(
    r"^\|\s*`([^`]+)`\s*\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|\s*$"
)


def split_frontmatter(text: str) -> tuple[dict, str]:
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    return yaml.safe_load(match.group(1)) or {}, match.group(2).strip()


@dataclass(frozen=True)
class SkillTool:
    tool: str
    execution: str  # always | conditional
    condition: str
    condition_tool: str | None
    role: str


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    category: str
    body: str
    tools: tuple[SkillTool, ...] = ()


@dataclass(frozen=True)
class Param:
    name: str
    annotation: str | None
    required: bool
    default: str | None  # source repr of the default


@dataclass(frozen=True)
class Tool:
    name: str
    category: str
    signature: str
    docstring: str
    params: tuple[Param, ...]
    outputs: tuple[str, ...]  # dict keys returned, or ("result",)
    code: str  # function source without docstring
    param_docs: dict[str, str] = field(
        default_factory=dict
    )  # Google-style "Args:" lines

    @property
    def summary(self) -> str:
        return (
            self.docstring.strip().splitlines()[0]
            if self.docstring.strip()
            else ""
        )

    def output_expr(self, var: str, output: str) -> str:
        return var if self.outputs == ("result",) else f"{var}[{output!r}]"


@dataclass
class SkillCatalog:
    skills: dict[str, Skill] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> "SkillCatalog":
        catalog = cls()
        for path in sorted(root.rglob("*.md")):
            meta, body = split_frontmatter(path.read_text("utf-8"))
            name = meta.get("name") or path.stem
            rows = []
            for line in body.splitlines():
                if match := _TABLE_ROW.match(line.strip()):
                    tool, mode, condition, cond_tool, role = (
                        g.strip() for g in match.groups()
                    )
                    rows.append(
                        SkillTool(
                            tool=tool,
                            execution="conditional"
                            if "조건" in mode or "conditional" in mode
                            else "always",
                            condition=condition,
                            condition_tool=cond_tool.strip("`")
                            if cond_tool not in {"", "없음", "-"}
                            else None,
                            role=role,
                        )
                    )
            catalog.skills[name] = Skill(
                name,
                meta.get("description", ""),
                path.parent.name,
                body,
                tuple(rows),
            )
        return catalog

    def index(self) -> str:
        return "\n".join(
            f"- `{s.name}`: {s.description}" for s in self.skills.values()
        )


def _parse_tool(path: Path) -> Tool:
    source = path.read_text("utf-8")
    module = ast.parse(source)
    funcs = [
        n
        for n in module.body
        if isinstance(n, ast.FunctionDef) and n.name == path.stem
    ]
    if len(funcs) != 1:
        raise ValueError(f"{path}: expected one function named {path.stem}")
    fn = funcs[0]
    docstring = ast.get_docstring(fn) or ""
    lines = source.splitlines()
    body_start = fn.body[0]
    if docstring and isinstance(body_start, ast.Expr):
        del lines[body_start.lineno - 1 : body_start.end_lineno]
        if len(fn.body) == 1:
            lines.insert(
                body_start.lineno - 1, " " * body_start.col_offset + "pass"
            )
    start = (
        fn.decorator_list[0].lineno if fn.decorator_list else fn.lineno
    ) - 1
    docstring_lines = (
        (body_start.end_lineno or body_start.lineno) - body_start.lineno + 1
        if docstring
        else 0
    )
    end = (fn.end_lineno or fn.lineno) - docstring_lines
    code = "\n".join(lines[start:end])

    args = fn.args
    defaults = [None] * (len(args.args) - len(args.defaults)) + list(
        args.defaults
    )
    params = [
        Param(
            a.arg,
            ast.unparse(a.annotation) if a.annotation else None,
            d is None,
            ast.unparse(d) if d else None,
        )
        for a, d in zip(args.args, defaults, strict=True)
    ]
    params += [
        Param(
            a.arg,
            ast.unparse(a.annotation) if a.annotation else None,
            d is None,
            ast.unparse(d) if d else None,
        )
        for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True)
    ]
    keys: list[str] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            keys += [
                k.value
                for k in node.value.keys
                if isinstance(k, ast.Constant)
                and isinstance(k.value, str)
                and k.value not in keys
            ]
    signature = f"{fn.name}({ast.unparse(fn.args)})" + (
        f" -> {ast.unparse(fn.returns)}" if fn.returns else ""
    )
    return Tool(
        fn.name,
        path.parent.name,
        signature,
        docstring,
        tuple(params),
        tuple(keys) or ("result",),
        code,
        _arg_docs(docstring),
    )


def _arg_docs(docstring: str) -> dict[str, str]:
    docs, inside = {}, False
    for line in docstring.splitlines():
        stripped = line.strip()
        if stripped in {"Args:", "Arguments:", "Parameters:"}:
            inside = True
            continue
        if inside:
            if not stripped or (
                not line.startswith((" ", "\t")) and stripped.endswith(":")
            ):
                if stripped.endswith(":"):
                    break
                continue
            if match := re.match(r"(\w+)\s*(?:\([^)]*\))?:\s*(.*)", stripped):
                docs[match.group(1)] = match.group(2)
    return docs


@dataclass
class ToolCatalog:
    tools: dict[str, Tool] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> "ToolCatalog":
        catalog = cls()
        for path in sorted(root.rglob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                tool = _parse_tool(path)
                catalog.tools[tool.name] = tool
            except (SyntaxError, ValueError) as exc:
                catalog.errors[str(path)] = str(exc)
        return catalog

    def describe(self, name: str) -> str:
        tool = self.tools[name]
        outputs = list(tool.outputs)
        return f"{tool.signature}\noutputs: {outputs}\n\n{tool.docstring}"


class AssetLoader:
    """Parsed view of a directory, reloaded when a file changes.

    Changes are checked at most every few seconds.
    """

    def __init__(self, root: Path, factory, check_seconds: float = 5.0):
        self.root, self.factory, self.check_seconds = (
            root,
            factory,
            check_seconds,
        )
        self._stamp: tuple | None = None
        self._checked = 0.0
        self._value = None

    def get(self):
        now = time.monotonic()
        if (
            self._value is not None
            and now - self._checked < self.check_seconds
        ):
            return self._value
        self._checked = now
        files = sorted(self.root.rglob("*")) if self.root.exists() else []
        stamp = tuple(
            (str(p), p.stat().st_mtime_ns) for p in files if p.is_file()
        )
        if stamp != self._stamp:
            self._value, self._stamp = self.factory(self.root), stamp
        return self._value
