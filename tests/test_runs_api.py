import base64
import io

import pytest
from PIL import Image as PILImage
from pydantic import ValidationError

from api_service.schemas.sessions import RunCreate
from api_service.services import hitl
from core.config import ModelSpec, Settings
from core.images import MAX_SIDE, ImageError, prepare

PLAN = {
    "type": "plan_approval",
    "interrupt_id": "i1",
    "candidates": [
        {
            "input_values": {},
            "input_slots": [{"key": "0.0.lot_cd", "required": True}],
            "calls": [
                {
                    "params": [
                        {
                            "key": "0.0.lot_cd",
                            "source": "input",
                            "type": "str",
                        },
                        {"key": "1.0.n", "source": "literal", "type": "int"},
                    ]
                }
            ],
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


def test_plan_replies_are_checked_against_the_question():
    ok = {
        "action": "approve",
        "index": 0,
        "input_values": {"0.0.lot_cd": "L1"},
    }
    assert hitl.validate(PLAN, ok) == []
    missing = hitl.validate(PLAN, {"action": "approve", "index": 0})
    assert missing[0]["field"] == "value.input_values.0.0.lot_cd"
    assert hitl.validate(PLAN, {"action": "approve", "index": 3})
    unknown = {**ok, "overrides": {"9.9.x": 1}}
    assert hitl.validate(PLAN, unknown)[0]["field"].startswith(
        "value.overrides"
    )
    assert hitl.validate(PLAN, {"action": "revise", "feedback": ""})


def test_typed_text_replies_to_the_pending_question():
    assert hitl.from_text(PLAN, "LOT 바꿔") == {
        "action": "revise",
        "feedback": "LOT 바꿔",
    }
    code = {"type": "code_approval"}
    assert hitl.from_text(code, "그만") == {
        "approve": False,
        "feedback": "그만",
    }
    question = {"type": "question", "fields": [{"key": "lot"}]}
    assert hitl.from_text(question, "L1") == {"lot": "L1"}
    assert hitl.validate({"type": "code_approval"}, {"approve": "y"})


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


def test_reply_shapes_follow_the_question_type():
    def fields(waiting, value):
        return {e["field"] for e in hitl.validate(waiting, value)}

    code = {"type": "code_approval"}
    assert fields(code, {"approve": True, "code": "x = 1"}) == set()
    assert fields(code, {"approve": "y"}) == {"value.approve"}
    assert fields(code, {"approve": True, "tags": []}) == {"value.tags"}
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


def test_openapi_documents_the_reply_models():
    from fastapi import FastAPI

    from api_service.app import mount_api

    app = FastAPI()
    mount_api(app, Settings())
    spec = app.openapi()["components"]["schemas"]
    for name in [
        "PlanApproveReply",
        "PlanReviseReply",
        "PlanCancelReply",
        "CodeApprovalReply",
        "WorkflowSaveReply",
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


def test_every_question_the_agent_asks_has_a_reply_model_and_rules():
    from api_service.schemas.hitl import REPLIES
    from api_service.services.hitl import REPLY_RULES
    from core.contracts.hitl import REQUESTS

    paused = _asked_question_types()
    assert paused, "no interrupts found: the scan is broken"
    assert paused <= set(REQUESTS), paused - set(REQUESTS)
    asked = paused - {"executor_wait"}  # resumed by events, not people
    assert asked <= set(REPLIES), asked - set(REPLIES)
    assert set(REPLY_RULES) == set(REPLIES)
    assert set(REPLIES) == set(REQUESTS) - {"executor_wait"}


def test_pause_models_read_what_the_tools_raise():
    from pydantic import TypeAdapter

    from core.contracts.hitl import PauseRequest

    pause = TypeAdapter(PauseRequest)
    question = pause.validate_python(
        {
            "interrupt_id": "i",
            "type": "question",
            "question": "LOT?",
            "options": [],
            "fields": [
                {
                    "key": "lot",
                    "label": "LOT",
                    "type": "string",
                    "required": True,
                }
            ],
        }
    )
    assert question.type == "question"
    wait = pause.validate_python(
        {
            "interrupt_id": "i",
            "kind": "executor",
            "type": "executor_wait",
            "execution_id": "x",
            "operation_id": None,
            "steps": ["finalize"],
        }
    )
    assert wait.type == "executor_wait"
    with pytest.raises(ValidationError):
        pause.validate_python({"interrupt_id": "i", "type": "nope"})
    with pytest.raises(ValidationError):  # a question needs its text
        pause.validate_python({"interrupt_id": "i", "type": "question"})


def test_plan_approve_keys_go_where_they_belong():
    def errors(**value):
        reply = {"action": "approve", "index": 0, **value}
        return {
            e["field"]: e["message"] for e in hitl.validate(PLAN_FULL, reply)
        }

    ok = {"0.0.lot_cd": "L1"}
    assert errors(input_values=ok, overrides={"1.0.n": 5, "1.0.k": 3}) == {}
    # an input slot is filled with input_values, not overrides
    assert (
        "input_values"
        in errors(input_values=ok, overrides={"0.0.lot_cd": "L2"})[
            "value.overrides.0.0.lot_cd"
        ]
    )
    # a fixed value is changed with overrides, not input_values
    wrong = errors(input_values={**ok, "1.0.n": 5})
    assert "overrides" in wrong["value.input_values.1.0.n"]
    # an earlier call's output cannot be changed; unknown keys are refused
    assert (
        "바꿀 수 없"
        in errors(input_values=ok, overrides={"1.0.data": 1})[
            "value.overrides.1.0.data"
        ]
    )
    assert (
        "없는 입력칸"
        in errors(input_values={**ok, "0.0.lot": "x"})[
            "value.input_values.0.0.lot"
        ]
    )


def test_plan_approve_values_match_basic_types():
    def errors(inputs, overrides):
        reply = {
            "action": "approve",
            "input_values": inputs,
            "overrides": overrides,
        }
        return {e["field"] for e in hitl.validate(PLAN_FULL, reply)}

    assert errors({"0.0.lot_cd": "123"}, {"1.0.n": 5, "1.0.k": None}) == set()
    assert errors({"0.0.lot_cd": 123}, {}) == {"value.input_values.0.0.lot_cd"}
    assert errors({"0.0.lot_cd": "L1"}, {"1.0.n": "5"}) == {
        "value.overrides.1.0.n"
    }
    assert errors({"0.0.lot_cd": "L1"}, {"1.0.n": True}) == {
        "value.overrides.1.0.n"
    }
    # not a plain annotation (or none): any value
    assert errors({"0.0.lot_cd": "L1"}, {"1.0.any": {"x": [1]}}) == set()


PLAN_FULL = {
    "type": "plan_approval",
    "candidates": [
        {
            "input_values": {},
            "input_slots": [{"key": "0.0.lot_cd", "required": True}],
            "calls": [
                {
                    "params": [
                        {
                            "key": "0.0.lot_cd",
                            "source": "input",
                            "type": "str | None",
                        },
                        {
                            "key": "1.0.data",
                            "source": "tool_output",
                            "type": None,
                        },
                        {"key": "1.0.n", "source": "literal", "type": "int"},
                        {
                            "key": "1.0.k",
                            "source": "default",
                            "type": "int | None",
                        },
                        {
                            "key": "1.0.any",
                            "source": "default",
                            "type": "pd.DataFrame",
                        },
                    ]
                }
            ],
        }
    ],
}


def test_apply_overrides_refuses_what_it_cannot_apply():
    import pytest

    from agent import plan_format

    document = {
        "workflow": {
            "steps": [
                {"skill": "s", "tools": [{"tool": "a", "arguments": {}}]},
                {
                    "skill": "s",
                    "tools": [
                        {
                            "tool": "b",
                            "arguments": {
                                "data": {
                                    "source": "tool_output",
                                    "step_index": 0,
                                    "tool_index": 0,
                                    "output": "data",
                                }
                            },
                        }
                    ],
                },
            ]
        }
    }
    _, values = plan_format.apply_overrides(document, {}, {"0.0.n": 1})
    with pytest.raises(plan_format.PlanFormatError):
        plan_format.apply_overrides(document, {}, {"1.0.data": 1})
    with pytest.raises(plan_format.PlanFormatError):
        plan_format.apply_overrides(document, {}, {"9.9.x": 1})
