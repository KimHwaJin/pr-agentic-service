"""A tool file that does not parse is reported as broken, not as missing."""

from src.dtest.core.assets import ToolCatalog
from src.dtest.core.workflows import spec


def _write(root, name, source):
    (root / "eda").mkdir(parents=True, exist_ok=True)
    (root / "eda" / f"{name}.py").write_text(source, "utf-8")


def test_broken_file_is_tracked_by_name(tmp_path):
    _write(tmp_path, "good", "def good(x):\n    return {'y': x}\n")
    _write(tmp_path, "bad", "def bad(x:\n    return 1\n")
    catalog = ToolCatalog.load(tmp_path)
    assert "good" in catalog.tools
    assert "bad" not in catalog.tools
    assert "bad" in catalog.broken
    assert "읽지 못했습니다" in catalog.missing("bad")
    assert catalog.missing("nothing") == "'nothing' tool이 없습니다."


def test_later_root_fixes_or_breaks_a_tool(tmp_path):
    base, ext = tmp_path / "base", tmp_path / "ext"
    _write(base, "t", "def t(x:\n")
    _write(ext, "t", "def t(x):\n    return x\n")
    fixed = ToolCatalog.load_many([base, ext])
    assert "t" in fixed.tools and "t" not in fixed.broken
    broken = ToolCatalog.load_many([ext, base])
    assert "t" not in broken.tools and "t" in broken.broken


def test_workflow_validation_names_the_load_failure(adaptive, skills, tools):
    name = adaptive["workflow"]["steps"][0]["tools"][0]["tool"]
    broken = ToolCatalog(
        tools={k: v for k, v in tools.tools.items() if k != name},
        broken={name: "invalid syntax"},
    )
    errors = spec.validate(adaptive, skills, broken)
    assert any(
        f"tool '{name}' failed to load: invalid syntax" in e for e in errors
    ), errors
    assert not any("unknown tool" in e for e in errors)
