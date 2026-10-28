import json
from pathlib import Path

import pytest

from src.dtest.core.assets import SkillCatalog, ToolCatalog

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def skills() -> SkillCatalog:
    return SkillCatalog.load(ROOT / "src/dtest/assets/skills")


@pytest.fixture(scope="session")
def tools() -> ToolCatalog:
    return ToolCatalog.load(ROOT / "src/dtest/assets/tools")


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
