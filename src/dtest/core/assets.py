"""Skill (.md) and Tool (.py) catalogs read from configurable directories.

Skills: ``<root>/<category>/<name>.md`` with ``name``/``description``
frontmatter. Analysis skills carry a ``## Tool list`` table whose columns
are found by header name, in any order: Tool (`name` in backticks),
실행 방식, 실행 조건, condition_tool, 역할 (or execution, condition, role).
Any other column is kept per tool in ``SkillTool.extra``.
Tools: ``<root>/<category>/<tool>.py`` holding one top-level function named
like the file. Imports live inside the function; the executor receives the
function without its docstring.
"""

import ast
import logging
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.S)
_SEPARATOR = re.compile(r"^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?$")
_TOOL_NAME = re.compile(r"^`([^`]+)`$")
# header name -> SkillTool field; other headers go to SkillTool.extra
_COLUMNS = {
    "tool": "tool",
    "실행 방식": "execution",
    "execution": "execution",
    "실행 조건": "condition",
    "condition": "condition",
    "condition_tool": "condition_tool",
    "역할": "role",
    "role": "role",
}
log = logging.getLogger(__name__)


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
    extra: tuple[tuple[str, str], ...] = ()  # other columns, in table order


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
    errors: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> "SkillCatalog":
        catalog = cls()
        for path in sorted(root.rglob("*.md")):
            meta, body = split_frontmatter(path.read_text("utf-8"))
            name = meta.get("name") or path.stem
            rows, problems = tool_table(body)
            if problems:
                catalog.errors[str(path)] = "; ".join(problems)
                log.warning("skill %s: %s", path, "; ".join(problems))
            catalog.skills[name] = Skill(
                name,
                meta.get("description", ""),
                path.parent.name,
                body,
                tuple(rows),
            )
        return catalog

    @classmethod
    def load_many(cls, roots: Sequence[Path]) -> "SkillCatalog":
        """Roots in order; a later root replaces a skill of the same name
        (an extension can override a base skill)."""
        catalog = cls()
        for root in roots:
            if root.exists():
                part = cls.load(root)
                catalog.skills.update(part.skills)
                catalog.errors.update(part.errors)
        return catalog

    def index(self) -> str:
        return "\n".join(
            f"- `{s.name}`: {s.description}" for s in self.skills.values()
        )


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def tool_table(body: str) -> tuple[list[SkillTool], list[str]]:
    """Rows of the tables whose header has a Tool column, and what could
    not be read (rows without a backticked tool name, missing cells)."""
    rows: list[SkillTool] = []
    problems: list[str] = []
    lines = body.splitlines()
    i = 0
    while i < len(lines) - 1:
        header = lines[i].strip()
        if not (
            header.startswith("|") and _SEPARATOR.match(lines[i + 1].strip())
        ):
            i += 1
            continue
        names = _cells(header)
        fields = [_COLUMNS.get(n.lower(), _COLUMNS.get(n)) for n in names]
        i += 2
        if "tool" not in fields:
            continue
        while i < len(lines) and lines[i].strip().startswith("|"):
            cells = _cells(lines[i])
            i += 1
            if len(cells) != len(names):
                problems.append(
                    f"칸 수가 헤더({len(names)})와 다른 행: {cells[0]}"
                )
                continue
            values: dict[str, str] = {}
            extra = []
            for name, key, cell in zip(names, fields, cells, strict=True):
                if key:
                    values[key] = cell
                elif cell:
                    extra.append((name, cell))
            if not (match := _TOOL_NAME.match(values["tool"])):
                problems.append(
                    f"tool 이름에 백틱이 없는 행: {values['tool']}"
                )
                continue
            mode = values.get("execution", "")
            cond_tool = values.get("condition_tool", "")
            rows.append(
                SkillTool(
                    tool=match.group(1),
                    execution="conditional"
                    if "조건" in mode or "conditional" in mode
                    else "always",
                    condition=values.get("condition", ""),
                    condition_tool=cond_tool.strip("`")
                    if cond_tool not in {"", "없음", "-"}
                    else None,
                    role=values.get("role", ""),
                    extra=tuple(extra),
                )
            )
    return rows, problems


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

    @classmethod
    def load_many(cls, roots: Sequence[Path]) -> "ToolCatalog":
        """Roots in order; a later root replaces a tool of the same name."""
        catalog = cls()
        for root in roots:
            if root.exists():
                part = cls.load(root)
                catalog.tools.update(part.tools)
                catalog.errors.update(part.errors)
        return catalog

    def describe(self, name: str) -> str:
        tool = self.tools[name]
        outputs = list(tool.outputs)
        return f"{tool.signature}\noutputs: {outputs}\n\n{tool.docstring}"

    def summary(self, name: str) -> str:
        """One line: name, first docstring line, outputs."""
        tool = self.tools[name]
        first = tool.docstring.splitlines()[0] if tool.docstring else ""
        return f"- `{name}`: {first} (outputs: {list(tool.outputs)})"


class AssetLoader:
    """Parsed view of a directory, reloaded when a file changes.

    Changes are checked at most every few seconds.
    """

    def __init__(
        self,
        root: Path | Sequence[Path],
        factory,
        check_seconds: float = 5.0,
    ):
        """``factory`` gets ``root`` as given: a path, or the roots."""
        self.root, self.factory, self.check_seconds = (
            root,
            factory,
            check_seconds,
        )
        self._roots = [root] if isinstance(root, Path) else list(root)
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
        files = sorted(
            p for r in self._roots if r.exists() for p in r.rglob("*")
        )
        stamp = tuple(
            (str(p), p.stat().st_mtime_ns) for p in files if p.is_file()
        )
        if stamp != self._stamp:
            self._value, self._stamp = self.factory(self.root), stamp
        return self._value
