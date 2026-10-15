"""Checks a HITL answer against the question the run is waiting on.

``run.waiting`` holds the question (type, candidates, fields ...), so a wrong
answer is refused here with field-level errors instead of reaching the agent
and coming back as the same question.
"""

from collections.abc import Mapping
from typing import Any

from pydantic import TypeAdapter, ValidationError

from api_service.schemas.answers import ANSWERS

Errors = list[dict[str, str]]


def _err(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def validate(waiting: dict[str, Any], value: Any) -> Errors:
    """Shape first (the answer model of this question type), then content
    (fields, candidates and inputs of this very question)."""
    kind = waiting.get("type", "")
    model = ANSWERS.get(kind)
    if model is None:
        return []
    try:
        TypeAdapter(model).validate_python(value, strict=True)
    except ValidationError as exc:
        if kind == "question":  # neither branch of str | dict fits
            return [
                _err("value", "답 문자열 또는 {필드: 값} 객체가 필요합니다")
            ]
        return [_shape_error(e, kind) for e in exc.errors()]
    check = {
        "question": _question,
        "plan_approval": _plan,
        "workflow_save": _workflow,
    }.get(kind)
    return check(waiting, value) if check else []


_MESSAGES = {
    "missing": "필수 입력입니다",
    "extra_forbidden": "알 수 없는 항목입니다",
    "bool_type": "true 또는 false가 필요합니다",
    "int_type": "정수여야 합니다",
    "greater_than_equal": "0 이상이어야 합니다",
    "string_type": "문자열이어야 합니다",
    "dict_type": "객체가 필요합니다",
    "model_type": "객체가 필요합니다",
    "model_attributes_type": "객체가 필요합니다",
    "list_type": "목록이어야 합니다",
    "union_tag_invalid": "approve, revise, cancel 중 하나",
    "union_tag_not_found": "approve, revise, cancel 중 하나",
}
_PLAN_TAGS = {"approve", "revise", "cancel"}


def _shape_error(error: Mapping[str, Any], kind: str) -> dict[str, str]:
    loc = [str(p) for p in error["loc"]]
    if kind == "plan_approval":
        if loc and loc[0] in _PLAN_TAGS:
            loc = loc[1:]  # the plan answer's union tag, not a field
        if error["type"].startswith("union_tag"):
            loc = ["action"]
    field = ".".join(["value", *loc])
    return _err(field, _MESSAGES.get(error["type"], error["msg"]))


def from_text(waiting: dict[str, Any], text: str) -> Any:
    """What a chat message typed while a question is pending answers."""
    kind = waiting.get("type")
    if kind == "question":
        fields = [f.get("key") for f in waiting.get("fields") or []]
        return {fields[0]: text} if len(fields) == 1 else text
    if kind == "plan_approval":
        return {"action": "revise", "feedback": text}
    return {"approve": False, "feedback": text}


def _question(waiting: dict[str, Any], value: Any) -> Errors:
    fields = waiting.get("fields") or []
    if not fields:
        if isinstance(value, str) and value.strip():
            return []
        if isinstance(value, dict):
            return []
        return [_err("value", "답변을 입력하세요")]
    if not isinstance(value, dict):
        if len(fields) == 1 and isinstance(value, str) and value.strip():
            return []
        return [_err("value", "fields의 key로 된 객체가 필요합니다")]
    return [
        _err(f"value.{f['key']}", "필수 입력입니다")
        for f in fields
        if f.get("required") and _empty(value.get(f.get("key")))
    ]


def _plan(waiting: dict[str, Any], value: Any) -> Errors:
    action = value["action"]
    if action == "cancel":
        return []
    if action == "revise":
        if _empty(value.get("feedback")):
            return [_err("value.feedback", "수정 요청 내용을 입력하세요")]
        return []
    candidates = waiting.get("candidates") or []
    index = value.get("index", 0)
    if not 0 <= index < len(candidates):
        return [
            _err("value.index", f"0~{len(candidates) - 1} 사이여야 합니다")
        ]
    candidate = candidates[index]
    errors: Errors = []
    inputs = value.get("input_values") or {}
    overrides = value.get("overrides") or {}
    params = {
        p["key"]
        for call in candidate.get("calls") or []
        for p in call.get("params") or []
    }
    errors += [
        _err(f"value.overrides.{key}", "이 계획에 없는 파라미터입니다")
        for key in overrides
        if params and key not in params
    ]
    given = {**(candidate.get("input_values") or {}), **inputs, **overrides}
    errors += [
        _err(f"value.input_values.{slot['key']}", "필수 입력입니다")
        for slot in candidate.get("input_slots") or []
        if slot.get("required")
        and _empty(given.get(slot["key"]))
        and _empty(slot.get("value"))
    ]
    return errors


def _workflow(waiting: dict[str, Any], value: Any) -> Errors:
    queries = value.get("user_queries")
    if (
        value["approve"]
        and queries is not None
        and not (queries and all(q.strip() for q in queries))
    ):
        return [_err("value.user_queries", "질문 예시를 1개 이상 입력하세요")]
    return []
