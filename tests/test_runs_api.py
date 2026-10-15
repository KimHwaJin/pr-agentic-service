import base64
import io

import pytest
from PIL import Image as PILImage
from pydantic import ValidationError

from api_service.schemas.sessions import RunCreate
from api_service.services import answers
from core.config import ModelSpec, Settings
from core.images import MAX_SIDE, ImageError, prepare

PLAN = {
    "type": "plan_approval",
    "interrupt_id": "i1",
    "candidates": [
        {
            "input_values": {},
            "input_slots": [{"key": "0.0.lot_cd", "required": True}],
            "calls": [{"params": [{"key": "0.0.lot_cd"}, {"key": "1.0.n"}]}],
        }
    ],
}


def test_run_body_needs_exactly_one_of_input_and_command():
    RunCreate.model_validate({"input": {"content": "hi"}})
    resume = {"resume": {"interrupt_id": "i", "value": {}}}
    RunCreate.model_validate({"command": resume})
    for body in ({}, {"input": {"content": "hi"}, "command": resume}):
        with pytest.raises(ValidationError):
            RunCreate.model_validate(body)
    with pytest.raises(ValidationError):
        RunCreate.model_validate({"command": resume, "model": "x"})


def test_content_blocks_split_text_and_images():
    body = RunCreate.model_validate(
        {
            "input": {
                "content": [
                    {"type": "text", "text": "이 맵 봐줘"},
                    {
                        "type": "image",
                        "base64": "QUJD",
                        "mime_type": "image/png",
                    },
                ]
            }
        }
    )
    assert body.input is not None
    assert body.input.text == "이 맵 봐줘" and len(body.input.images) == 1
    with pytest.raises(ValidationError):  # images alone, no text
        RunCreate.model_validate(
            {
                "input": {
                    "content": [
                        {
                            "type": "image",
                            "base64": "QUJD",
                            "mime_type": "image/png",
                        }
                    ]
                }
            }
        )


def test_plan_answers_are_checked_against_the_question():
    ok = {
        "action": "approve",
        "index": 0,
        "input_values": {"0.0.lot_cd": "L1"},
    }
    assert answers.validate(PLAN, ok) == []
    missing = answers.validate(PLAN, {"action": "approve", "index": 0})
    assert missing[0]["field"] == "value.input_values.0.0.lot_cd"
    assert answers.validate(PLAN, {"action": "approve", "index": 3})
    unknown = {**ok, "overrides": {"9.9.x": 1}}
    assert answers.validate(PLAN, unknown)[0]["field"].startswith(
        "value.overrides"
    )
    assert answers.validate(PLAN, {"action": "revise", "feedback": ""})


def test_typed_text_answers_the_pending_question():
    assert answers.from_text(PLAN, "LOT 바꿔") == {
        "action": "revise",
        "feedback": "LOT 바꿔",
    }
    code = {"type": "code_approval"}
    assert answers.from_text(code, "그만") == {
        "approve": False,
        "feedback": "그만",
    }
    question = {"type": "question", "fields": [{"key": "lot"}]}
    assert answers.from_text(question, "L1") == {"lot": "L1"}
    assert answers.validate({"type": "code_approval"}, {"approve": "y"})


def test_model_catalog_needs_one_default():
    two = [
        ModelSpec(name="a", default=True),
        ModelSpec(name="b", default=True),
    ]
    with pytest.raises(ValidationError):
        Settings(models=two)
    settings = Settings(models=[ModelSpec(name="a", default=True)])
    assert settings.model(None) is not None and settings.model("zz") is None


def _png(width: int, height: int) -> str:
    out = io.BytesIO()
    PILImage.new("RGB", (width, height)).save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode()


def test_images_are_checked_and_shrunk():
    big = prepare(_png(3000, 1000), "image/png", 10_000_000)
    assert max(big.width, big.height) == MAX_SIDE
    with pytest.raises(ImageError):  # PNG content declared as JPEG
        prepare(_png(10, 10), "image/jpeg", 10_000_000)
    with pytest.raises(ImageError):
        prepare(base64.b64encode(b"not an image").decode(), "image/png", 999)


def test_images_reach_only_vision_models_for_recent_turns():
    import asyncio
    from types import SimpleNamespace
    from typing import Any, cast

    from langchain_core.messages import AIMessage, HumanMessage

    from agent.middleware.persona import _with_images

    def turn(image_id: str) -> HumanMessage:
        return HumanMessage(
            [
                {"type": "text", "text": "봐줘"},
                {
                    "type": "image",
                    "file_id": image_id,
                    "mime_type": "image/png",
                    "extras": {"name": f"{image_id}.png"},
                },
            ]
        )

    messages = [turn("old"), AIMessage("a"), turn("new"), AIMessage("b")]
    images = SimpleNamespace(
        get=lambda i: _ready(SimpleNamespace(session_id="s")),
        read_base64=lambda image: "QUJD",
    )

    def ctx(model: str) -> Any:
        settings = Settings(
            models=[
                ModelSpec(name="text", default=True),
                ModelSpec(name="vl", input=["text", "image"], max_images=8),
            ],
            image_context_turns=1,
        )
        services = SimpleNamespace(settings=settings, images=images)
        return cast(
            Any,
            SimpleNamespace(
                services=services, model=model, session_id="s", cache={}
            ),
        )

    out = asyncio.run(_with_images(messages, ctx("vl")))
    assert out[0].content[1] == {"type": "text", "text": "[이미지: old.png]"}
    assert out[2].content[1]["base64"] == "QUJD"
    text_only = asyncio.run(_with_images(messages, ctx("text")))
    assert text_only[2].content[1]["type"] == "text"


async def _ready(value):
    return value


def test_answer_shapes_follow_the_question_type():
    def fields(waiting, value):
        return {e["field"] for e in answers.validate(waiting, value)}

    code = {"type": "code_approval"}
    assert fields(code, {"approve": True, "code": "x = 1"}) == set()
    assert fields(code, {"approve": "y"}) == {"value.approve"}
    assert fields(code, {"approve": True, "tags": []}) == {"value.tags"}
    memory = {"type": "memory_change"}
    assert fields(memory, {"approve": False, "feedback": "아니"}) == set()
    save = {"type": "workflow_save"}
    assert (
        fields(save, {"approve": True, "name": "n", "user_queries": ["q"]})
        == set()
    )
    assert fields(save, {"approve": True, "user_queries": ["q", 3]}) == {
        "value.user_queries.1"
    }
    assert fields(PLAN, {"action": "go"}) == {"value.action"}
    assert fields(PLAN, {"action": "approve", "index": "0"}) == {"value.index"}
    assert fields(PLAN, {"action": "cancel", "index": 0}) == {"value.index"}
    question = {"type": "question", "fields": []}
    assert fields(question, "네") == set()
    assert fields(question, 5) == {"value"}


def test_resume_value_is_kept_as_sent():
    for value in [
        {"action": "approve", "index": 1},
        {"approve": True},
        "L1",
        {"lot": "L1", "text": "메모"},
    ]:
        body = RunCreate.model_validate(
            {"command": {"resume": {"interrupt_id": "i", "value": value}}}
        )
        assert body.command is not None
        assert body.command.resume.value == value
        dumped = body.model_dump(mode="json")["command"]["resume"]["value"]
        assert dumped == value  # the idempotency hash sees the same body


def test_openapi_documents_the_answer_models():
    from fastapi import FastAPI

    from api_service.app import mount_api

    app = FastAPI()
    mount_api(app, Settings())
    spec = app.openapi()["components"]["schemas"]
    for name in [
        "PlanApprove",
        "PlanRevise",
        "PlanCancel",
        "CodeApprovalAnswer",
        "MemoryChangeAnswer",
        "WorkflowSaveAnswer",
    ]:
        assert name in spec, name


def _asked_question_types() -> set[str]:
    """``type`` of every interrupt({...}) the agent tools raise."""
    import ast

    from core.config import ROOT

    kinds: set[str] = set()
    for path in (ROOT / "src/agent/tools").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "interrupt"
                and node.args
                and isinstance(node.args[0], ast.Dict)
            ):
                for key, value in zip(
                    node.args[0].keys, node.args[0].values, strict=True
                ):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "type"
                        and isinstance(value, ast.Constant)
                        and isinstance(value.value, str)
                    ):
                        kinds.add(value.value)
    return kinds


def test_every_question_the_agent_asks_has_an_answer_model_and_rules():
    from api_service.schemas.answers import ANSWERS
    from api_service.services.answers import RULES

    asked = _asked_question_types() - {"executor_wait"}  # resumed by events
    assert asked, "no interrupts found: the scan is broken"
    assert asked <= set(ANSWERS), asked - set(ANSWERS)
    assert set(RULES) == set(ANSWERS)
