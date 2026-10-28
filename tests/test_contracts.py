"""The event contract covers every event the code sends."""

import ast
from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from src.dtest.core.config import ROOT
from src.dtest.core.contracts import events


def _emitted_types() -> set[str]:
    """Event type names passed to any ``.emit(...)`` call in src/."""
    found: set[str] = set()
    for path in (ROOT / "src").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "emit"
            ):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(
                        arg.value, str
                    ):
                        found.add(arg.value)
    return found


def test_every_emitted_event_type_has_a_model():
    emitted = _emitted_types() - {"activity"}  # emitted via a variable too
    assert emitted, "no emit calls found: the scan is broken"
    assert emitted <= set(events.EVENTS), emitted - set(events.EVENTS)
    assert "activity" in events.EVENTS


def test_check_refuses_unknown_types_and_wrong_shapes():
    events.check("run_status", {"status": "running"})
    events.check("memory_updated", {"action": "deleted", "item": {"id": "m1"}})
    with pytest.raises(events.UnknownEventType):
        events.check("nope", {})
    with pytest.raises(ValidationError):
        events.check("run_status", {"status": "sleeping"})
    with pytest.raises(ValidationError):
        events.check("tool_call", {"args": {}})  # no name


def test_stored_events_read_by_type():
    stored = TypeAdapter(list[events.StoredEvent])
    now = datetime.now(UTC)
    items = stored.validate_python(
        [
            {
                "id": 1,
                "type": "token",
                "data": {"text": "a"},
                "created_at": now,
            },
            {
                "id": 2,
                "type": "execution_completed",
                "data": {
                    "execution_id": "e",
                    "results": [
                        {
                            "call": 0,
                            "tool": "extract_data",
                            "status": "SUCCEEDED",
                        }
                    ],
                    "error": None,
                },
                "created_at": now,
            },
        ]
    )
    assert [type(i).__name__ for i in items] == [
        "TokenEvent",
        "ExecutionCompletedEvent",
    ]
