"""Skill (.md) and Tool (.py) catalogs read from configurable directories.

Skills: ``<root>/<category>/<name>.md`` with ``name``/``description``
frontmatter. Analysis skills carry a ``## Tool list`` table whose columns
are found by header name, in any order: Tool (`name` in backticks),
실행 방식, 실행 조건, condition_tool, 역할 (or execution, condition, role).
Any other column is kept per tool in ``SkillTool.extra``.
Tools: ``<root>/<category>/<tool>.py`` holding one top-level function named
like the file, plus any helpers it needs. The executor receives the file's
definitions (imports, functions, classes, assignments) without docstrings;
shared helpers come from ``<root>/_lib`` (see ``LIB`` below).
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
    # other top-level names the cell binds in the kernel (helpers,
    # constants), with their source, for the catalog-wide clash check
    names: tuple[tuple[str, str], ...] = ()

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
                log.warning(
                    "skill_invalid path=%s problems=%s",
                    path,
                    "; ".join(problems),
                )
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


# --- tool files -> cell code ------------------------------------------------
#
# A tool file is ``<tool>.py`` with one top-level function named like the
# file (the tool) and any number of helpers. The cell sent to the executor
# holds only the definitions: imports, functions, classes and assignments,
# in file order, with every docstring removed. Notes (bare strings), the
# ``if __name__ == "__main__":`` block and comments between definitions are
# left out; any other top-level statement (a call, a loop) breaks the tool,
# because the cell would behave differently from the file.
#
# Shared helpers live in ``<root>/_lib/<module>.py`` and are imported as
# ``from _lib.<module> import name``. That line is replaced by the helpers
# the tool uses (and what they use in turn), so each cell runs on its own.

LIB = "_lib"
OBSERVE_HELPER = "_agentic_observe"
# names the generated code itself binds in the kernel
_RESERVED = re.compile(rf"^(?:{OBSERVE_HELPER}|_r_s\d+_t\d+)$")
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_IMPORTS = (ast.Import, ast.ImportFrom)
_KEPT = (*_DEFS, *_IMPORTS, ast.Assign, ast.AnnAssign)


def _is_note(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _is_main_guard(node: ast.stmt) -> bool:
    test = node.test if isinstance(node, ast.If) else None
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "__main__"
    )


def _from_lib(node: ast.AST) -> bool:
    if isinstance(node, ast.ImportFrom):
        return node.level == 0 and (node.module or "").split(".")[0] == LIB
    return isinstance(node, ast.Import) and any(
        a.name.split(".")[0] == LIB for a in node.names
    )


def _bound(node: ast.stmt) -> list[str]:
    """Top-level names a kept statement binds."""
    if isinstance(node, _DEFS):
        return [node.name]
    if isinstance(node, ast.Import):
        return [(a.asname or a.name).split(".")[0] for a in node.names]
    if isinstance(node, ast.ImportFrom):
        return [a.asname or a.name for a in node.names]
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return [
        n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)
    ]


def _without_docstrings(lines: list[str], node: ast.stmt) -> str:
    """Source of ``node`` (decorators included) minus every docstring."""
    first = (
        node.decorator_list[0].lineno
        if isinstance(node, _DEFS) and node.decorator_list
        else node.lineno
    )
    last = node.end_lineno or node.lineno
    text = {n: lines[n - 1] for n in range(first, last + 1)}
    for inner in ast.walk(node):
        if not isinstance(inner, _DEFS) or not ast.get_docstring(inner):
            continue
        doc = inner.body[0]
        start, end = doc.lineno, doc.end_lineno or doc.lineno
        head = text[start][: doc.col_offset]
        tail = text[end][doc.end_col_offset or 0 :]
        if head.strip() or tail.split("#")[0].strip():
            raise ValueError(
                f"{inner.name}: docstring은 줄을 따로 써야 합니다 ({start}행)"
            )
        for n in range(start, end + 1):
            text[n] = None
        if len(inner.body) == 1:
            text[start] = head + "pass"
    return "\n".join(t for t in text.values() if t is not None)


@dataclass(frozen=True)
class _Unit:
    """One kept top-level statement."""

    code: str
    names: tuple[str, ...]
    uses: frozenset[str]
    is_import: bool
    is_def: bool
    # (module, name) for ``from _lib.<module> import name``
    lib: tuple[tuple[str, str], ...] = ()


def _units(path: Path, source: str) -> tuple[list[_Unit], list[str]]:
    """Kept statements of a file, and warnings."""
    module = ast.parse(source)
    lines = source.splitlines()
    units, warnings = [], []
    for node in module.body:
        if _is_note(node) or _is_main_guard(node):
            continue
        if not isinstance(node, _KEPT):
            raise ValueError(
                f"{path.name} {node.lineno}행: 파일 최상위에는 import, 함수, "
                f"클래스, 변수 대입만 둘 수 있습니다 ({type(node).__name__})"
            )
        for inner in ast.walk(node):
            if inner is not node and _from_lib(inner):
                raise ValueError(
                    f"{path.name} {inner.lineno}행: {LIB} 헬퍼는 파일 "
                    "최상위에서 가져옵니다"
                )
        lib: list[tuple[str, str]] = []
        if isinstance(node, ast.ImportFrom) and (
            node.level or (node.module or "").split(".")[0] == LIB
        ):
            if node.level or node.module == LIB:
                raise ValueError(
                    f"{path.name} {node.lineno}행: 헬퍼는 "
                    f"'from {LIB}.<모듈> import 이름'으로 가져옵니다"
                )
            for alias in node.names:
                if alias.asname or alias.name == "*":
                    raise ValueError(
                        f"{path.name} {node.lineno}행: {LIB} 헬퍼는 "
                        "별칭(as)이나 *로 가져올 수 없습니다"
                    )
                lib.append((node.module[len(LIB) + 1 :], alias.name))
        elif isinstance(node, ast.Import) and any(
            a.name.split(".")[0] == LIB for a in node.names
        ):
            raise ValueError(
                f"{path.name} {node.lineno}행: 헬퍼는 "
                f"'from {LIB}.<모듈> import 이름'으로 가져옵니다"
            )
        if isinstance(node, ast.Assign | ast.AnnAssign) and any(
            isinstance(n, ast.Call) for n in ast.walk(node)
        ):
            warnings.append(
                f"{path.name} {node.lineno}행: 최상위 대입에 함수 호출이 있어 "
                "툴을 실행할 때마다 다시 계산됩니다"
            )
        units.append(
            _Unit(
                code=_without_docstrings(lines, node),
                names=tuple(_bound(node)),
                uses=frozenset(
                    n.id for n in ast.walk(node) if isinstance(n, ast.Name)
                ),
                is_import=isinstance(node, _IMPORTS),
                is_def=isinstance(node, _DEFS),
                lib=tuple(lib),
            )
        )
    return units, warnings


class _Library:
    """``_lib`` helper modules: dotted name (``stats``, ``io.excel``) ->
    file. Pieces are cut per tool and cached per module."""

    def __init__(self, files: dict[str, Path] | None = None):
        self.files = files or {}
        self._parsed: dict[str, list[_Unit]] = {}

    @classmethod
    def of(cls, roots: Sequence[Path]) -> "_Library":
        """Later roots replace a module of the same name."""
        files: dict[str, Path] = {}
        for root in roots:
            base = root / LIB
            if base.is_dir():
                for path in sorted(base.rglob("*.py")):
                    parts = path.relative_to(base).with_suffix("").parts
                    if not any(p.startswith("_") for p in parts):
                        files[".".join(parts)] = path
        return cls(files)

    def _module(self, name: str) -> list[_Unit]:
        if name not in self._parsed:
            if name not in self.files:
                raise ValueError(f"헬퍼 모듈 {LIB}.{name}이 없습니다")
            path = self.files[name]
            units, warnings = _units(path, path.read_text("utf-8"))
            for warning in warnings:
                log.warning(
                    "tool_helper_warning path=%s warning=%s", path, warning
                )
            self._parsed[name] = units
        return self._parsed[name]

    def pieces(
        self, wanted: Sequence[tuple[str, str]]
    ) -> list[tuple[str, list[_Unit]]]:
        """Helper statements a tool needs, per module, dependencies first."""
        chosen: dict[str, set[int]] = {}
        order: list[str] = []

        def need(module: str, name: str, stack: tuple[str, ...]) -> None:
            if module in stack:
                cycle = " -> ".join((*stack, module))
                raise ValueError(f"헬퍼가 서로를 가져옵니다: {cycle}")
            units = self._module(module)
            todo = [i for i, u in enumerate(units) if name in u.names]
            if not todo:
                raise ValueError(f"{LIB}.{module}에 {name}이(가) 없습니다")
            picked = chosen.setdefault(module, set())
            while todo:
                i = todo.pop()
                if i in picked:
                    continue
                picked.add(i)
                for dep_module, dep_name in units[i].lib:
                    need(dep_module, dep_name, (*stack, module))
                for used in units[i].uses - set(units[i].names):
                    todo += [j for j, u in enumerate(units) if used in u.names]
            if module not in order:
                order.append(module)

        for module, name in wanted:
            need(module, name, ())
        return [
            (
                module,
                [
                    u
                    for i, u in enumerate(self._module(module))
                    if i in chosen[module] and not u.lib
                ],
            )
            for module in order
        ]


def _join(units: Sequence[_Unit]) -> str:
    out = ""
    for prev, unit in zip([None, *units], units, strict=False):
        if prev is not None:
            if prev.is_def or unit.is_def:
                out += "\n\n\n"
            elif prev.is_import != unit.is_import:
                out += "\n\n"
            else:
                out += "\n"
        out += unit.code
    return out


def _parse_tool(
    path: Path, library: _Library | None = None
) -> tuple["Tool", list[str]]:
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
    units, warnings = _units(path, source)
    own = [u for u in units if not u.lib]
    helpers = (library or _Library()).pieces(
        [pair for u in units for pair in u.lib]
    )
    if helpers:
        code = "\n\n\n".join(
            [
                f"# --- {LIB}/{module.replace('.', '/')}.py ---\n{_join(us)}"
                for module, us in helpers
            ]
            + [f"# --- {path.name} ---\n{_join(own)}"]
        )
    else:
        code = _join(own)
    names = tuple(
        (name, unit.code)
        for unit in [*own, *(u for _, us in helpers for u in us)]
        if not unit.is_import
        for name in unit.names
        if name != fn.name
    )

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
    compile(code, str(path), "exec")
    tool = Tool(
        fn.name,
        path.parent.name,
        signature,
        docstring,
        tuple(params),
        tuple(keys) or ("result",),
        code,
        _arg_docs(docstring),
        names,
    )
    return tool, warnings


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
    # tool name (file stem) -> why its file could not be read, so a lookup
    # says "failed to load" instead of "no such tool"
    broken: dict[str, str] = field(default_factory=dict)

    # tool file -> notes that do not stop it from loading
    warnings: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def load(
        cls, root: Path, library: "_Library | None" = None, *, check=True
    ) -> "ToolCatalog":
        """Tools under ``root``; any path part starting with ``_`` (such as
        ``_lib/``) is not a tool. Helpers come from ``library`` (default:
        ``root/_lib``)."""
        catalog = cls()
        library = library or _Library.of([root])
        for path in sorted(root.rglob("*.py")):
            if any(p.startswith("_") for p in path.relative_to(root).parts):
                continue
            try:
                tool, warnings = _parse_tool(path, library)
                catalog.tools[tool.name] = tool
                if warnings:
                    catalog.warnings[str(path)] = warnings
                    for warning in warnings:
                        log.warning(
                            "tool_load_warning path=%s warning=%s",
                            path,
                            warning,
                        )
            except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
                catalog.errors[str(path)] = str(exc)
                catalog.broken[path.stem] = str(exc)
                log.warning("tool_load_failed path=%s error=%s", path, exc)
        if check:
            catalog._check_names()
        return catalog

    @classmethod
    def load_many(cls, roots: Sequence[Path]) -> "ToolCatalog":
        """Roots in order; a later root replaces a tool of the same name,
        and a ``_lib`` helper module of the same name."""
        catalog = cls()
        roots = [r for r in roots if r.exists()]
        library = _Library.of(roots)
        for root in roots:
            part = cls.load(root, library, check=False)
            for name in part.tools:
                catalog.broken.pop(name, None)
            for name in part.broken:
                catalog.tools.pop(name, None)
            catalog.tools.update(part.tools)
            catalog.errors.update(part.errors)
            catalog.broken.update(part.broken)
            catalog.warnings.update(part.warnings)
        catalog._check_names()
        return catalog

    def _check_names(self) -> None:
        """Cells share one kernel: a helper must not replace another tool,
        the generated code's own names, or a different helper of the same
        name. Each offending tool is marked broken."""
        seen: dict[str, dict[str, str]] = {}  # name -> source -> tool
        for tool in self.tools.values():
            for name, source in tool.names:
                seen.setdefault(name, {}).setdefault(source, tool.name)
        problems: dict[str, list[str]] = {}
        for tool in self.tools.values():
            for name, source in tool.names:
                if name in self.tools:
                    why = f"'{name}'은(는) 다른 tool 이름입니다"
                elif _RESERVED.match(name):
                    why = f"'{name}'은(는) 생성 코드가 쓰는 이름입니다"
                elif len(seen[name]) > 1:
                    others = sorted(
                        t for s, t in seen[name].items() if s != source
                    )
                    why = (
                        f"'{name}'이(가) {', '.join(others)}에서 "
                        "다르게 정의되어 있습니다"
                    )
                else:
                    continue
                problems.setdefault(tool.name, []).append(why)
        for name, whys in problems.items():
            message = "커널 이름 충돌: " + "; ".join(whys)
            del self.tools[name]
            self.broken[name] = message
            self.errors[name] = message
            log.warning("tool_load_failed tool=%s error=%s", name, message)

    def missing(self, name: str) -> str:
        """Why ``name`` is not usable, in Korean for the model."""
        if name in self.broken:
            return f"'{name}' tool 파일을 읽지 못했습니다: {self.broken[name]}"
        return f"'{name}' tool이 없습니다."

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
