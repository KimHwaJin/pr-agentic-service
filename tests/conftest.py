import json
from pathlib import Path

import pytest

from core.assets import SkillCatalog, ToolCatalog

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def skills() -> SkillCatalog:
    return SkillCatalog.load(ROOT / "assets/skills")


@pytest.fixture(scope="session")
def tools() -> ToolCatalog:
    return ToolCatalog.load(ROOT / "assets/tools")


@pytest.fixture
def adaptive() -> dict:
    return json.loads(
        (ROOT / "tests/fixtures/workflow_adaptive.example.json").read_text(
            "utf-8"
        )
    )


@pytest.fixture
def static() -> dict:
    return json.loads(
        (ROOT / "tests/fixtures/workflow_static.example.json").read_text(
            "utf-8"
        )
    )
