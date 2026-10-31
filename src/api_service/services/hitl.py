"""Checks a HITL reply against the question the run is waiting on.

``run.waiting`` holds the question (type, candidates, fields ...), so a wrong
reply is refused here with field-level errors instead of reaching the agent
and coming back as the same question.

Adding a question type: its reply model goes in
``api_service.schemas.hitl.REPLIES``; here, a ``ReplyRules`` entry in
``REPLY_RULES`` says what else to check and what a typed chat message means.
Shape errors (unknown fields, wrong types, a missing tag) come from the
model; tests check that every question the agent asks has both.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cache
from typing import Any

from pydantic import TypeAdapter, ValidationError

from api_service.schemas.hitl import REPLIES

Errors = list[dict[str, str]]
Waiting = dict[str, Any]


def _err(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _no_check(waiting: Waiting, value: Any) -> Errors:
    return []


def _refuse(waiting: Waiting, text: str) -> Any:
    """Typed text on an approval: no, and why."""
    return {"approve": False, "feedback": text}


@dataclass(frozen=True)
class ReplyRules:
    # content checks against this very question (after the shape check)
    check: Callable[[Waiting, Any], Errors] = _no_check
    # what a chat message typed while the question is pending means
    from_text: Callable[[Waiting, str], Any] = _refuse
    # message when the reply fits no shape at all (None: per field)
    shape_message: str | None = None


def coerce(waiting: Waiting, value: Any) -> Any:
    """A plan approval's input_values / overrides typed as text become the
    parameter's type ("500" for an int is 500, "[1, 2]" for a list is a
    list), so a client sends what the user typed. A str parameter keeps
    the text ("123" stays a LOT code). Changes ``value`` in place."""
    if waiting.get("type") != "plan_approval" or not isinstance(value, dict):
        return value
    candidates = waiting.get("candidates") or []
    index = value.get("index", 0)
    if not isinstance(index, int) or not 0 <= index < len(candidates):
        return value
    params = {
        p["key"]: p
        for call in candidates[index].get("calls") or []
        for p in call.get("params") or []
    }
    for field in ("input_values", "overrides"):
        given = value.get(field)
        if not isinstance(given, dict):
            continue
        for key, text in given.items():
            if isinstance(text, str) and key in params:
                given[key] = _from_text(params[key].get("type"), text)
    return value


def _from_text(annotation: str | None, text: str) -> Any:
    if not annotation:
        return text
    names = [part.strip().split("[", 1)[0] for part in annotation.split("|")]
    if "str" in names or any(name not in _TYPES for name in names):
        return text
    if not text.strip():
        return None if "None" in names else text
    try:
        parsed = json.loads(text)
    except ValueError:
        if "bool" in names and text.strip().lower() in {"true", "false"}:
            return text.strip().lower() == "true"
        return text  # the type check names what was expected
    return parsed if _type_problem(annotation, parsed) is None else text


def validate(waiting: Waiting, value: Any) -> Errors:
    """Shape first (the reply model of this question type), then content
    (fields, candidates and inputs of this very question)."""
    kind = waiting.get("type", "")
    model = REPLIES.get(kind)
    if model is None:
        return []
    rules = REPLY_RULES.get(kind, ReplyRules())
    try:
        _adapter(kind).validate_python(value, strict=True)
    except ValidationError as exc:
        if rules.shape_message:
            return [_err("value", rules.shape_message)]
        return [_shape_error(e, kind, value) for e in exc.errors()]
    return rules.check(waiting, value)


def from_text(waiting: Waiting, text: str) -> Any:
    """What a chat message typed while a question is pending means."""
    kind = waiting.get("type", "")
    return REPLY_RULES.get(kind, ReplyRules()).from_text(waiting, text)


@cache
def _adapter(kind: str) -> TypeAdapter:
    return TypeAdapter(REPLIES[kind])


@cache
def _tags(kind: str) -> tuple[str, ...]:
    """Tag values of a discriminated reply union (empty otherwise)."""
    schema = _adapter(kind).json_schema()
    key = (schema.get("discriminator") or {}).get("propertyName")
    if not key:
        return ()
    defs = schema.get("$defs") or {}
    return tuple(  # in declaration order
        defs[branch["$ref"].rsplit("/", 1)[-1]]["properties"][key]["const"]
        for branch in schema.get("oneOf") or ()
    )


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
}


def _shape_error(
    error: Mapping[str, Any], kind: str, value: Any
) -> dict[str, str]:
    loc = [str(p) for p in error["loc"]]
    tags = _tags(kind)
    if error["type"] in {"union_tag_invalid", "union_tag_not_found"}:
        key = str((error.get("ctx") or {}).get("discriminator", "")).strip("'")
        return _err(f"value.{key}", f"{', '.join(tags)} 중 하나")
    if tags and loc and loc[0] in tags:
        loc = loc[1:]  # the union branch (tag value), not a field
    field = ".".join(["value", *loc])
    return _err(field, _MESSAGES.get(error["type"], error["msg"]))


def _question(waiting: Waiting, value: Any) -> Errors:
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


def _plan(waiting: Waiting, value: Any) -> Errors:
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
    params = {
        p["key"]: p
        for call in candidate.get("calls") or []
        for p in call.get("params") or []
    }
    slots = {s["key"] for s in candidate.get("input_slots") or []}
    inputs = value.get("input_values") or {}
    overrides = value.get("overrides") or {}
    errors: Errors = []
    for key, given in inputs.items():
        field = f"value.input_values.{key}"
        if key not in slots:
            errors.append(_err(field, _NOT_SLOT[_source(params, key)]))
        elif problem := _type_problem(params[key].get("type"), given):
            errors.append(_err(field, problem))
    for key, given in overrides.items():
        field = f"value.overrides.{key}"
        source = _source(params, key)
        if source not in _EDITABLE:
            errors.append(_err(field, _NOT_EDITABLE[source]))
        elif problem := _type_problem(params[key].get("type"), given):
            errors.append(_err(field, problem))
    given = {**(candidate.get("input_values") or {}), **inputs}
    return errors + [
        _err(f"value.input_values.{slot['key']}", "필수 입력입니다")
        for slot in candidate.get("input_slots") or []
        if slot.get("required")
        and _empty(given.get(slot["key"]))
        and _empty(slot.get("value"))
    ]


# overrides change what the agent decided: a fixed value or a tool default
_EDITABLE = {"literal", "default"}
_NOT_EDITABLE = {
    "input": "입력칸 값은 input_values로 보내세요",
    "tool_output": "앞 단계 결과로 정해지는 값이라 바꿀 수 없습니다",
    None: "이 계획에 없는 파라미터입니다",
}
_NOT_SLOT = {
    "literal": "입력칸이 아닙니다. Agent가 정한 값은 overrides로 바꾸세요",
    "default": "입력칸이 아닙니다. 기본값은 overrides로 바꾸세요",
    "tool_output": "앞 단계 결과로 정해지는 값이라 바꿀 수 없습니다",
    "input": "입력칸이 아닙니다",
    None: "이 계획에 없는 입력칸입니다",
}


def _source(params: dict[str, dict], key: str) -> str | None:
    param = params.get(key)
    return param.get("source") if param else None


# tool parameter annotations we can check; anything else is not checked
_TYPES: dict[str, tuple[type, ...]] = {
    "int": (int,),
    "float": (int, float),
    "bool": (bool,),
    "str": (str,),
    "list": (list,),
    "dict": (dict,),
    "None": (type(None),),
}
_TYPE_NAMES = {
    "int": "정수",
    "float": "숫자",
    "bool": "true/false",
    "str": "문자열",
    "list": "목록",
    "dict": "객체",
    "None": "null",
}


def _type_problem(annotation: str | None, value: Any) -> str | None:
    """A message when ``value`` fits none of the annotation's basic types.

    Only plain annotations such as ``int | None`` or ``list`` are checked;
    an unknown or missing annotation accepts any value.
    """
    if not annotation:
        return None
    names = [part.strip().split("[", 1)[0] for part in annotation.split("|")]
    if any(name not in _TYPES for name in names):
        return None
    for name in names:
        kinds = _TYPES[name]
        if isinstance(value, bool) and bool not in kinds:
            continue  # JSON true/false is not a number here
        if isinstance(value, kinds):
            return None
    return " 또는 ".join(_TYPE_NAMES[n] for n in names) + " 값이 필요합니다"


def _workflow(waiting: Waiting, value: Any) -> Errors:
    queries = value.get("user_queries")
    if (
        value["approve"]
        and queries is not None
        and not (queries and all(q.strip() for q in queries))
    ):
        return [_err("value.user_queries", "질문 예시를 1개 이상 입력하세요")]
    return []


def _question_text(waiting: Waiting, text: str) -> Any:
    fields = [f.get("key") for f in waiting.get("fields") or []]
    return {fields[0]: text} if len(fields) == 1 else text


def _plan_text(waiting: Waiting, text: str) -> Any:
    return {"action": "revise", "feedback": text}


# question type -> how to check its reply (the model is in REPLIES)
REPLY_RULES: dict[str, ReplyRules] = {
    "question": ReplyRules(
        check=_question,
        from_text=_question_text,
        shape_message="답 문자열 또는 {필드: 값} 객체가 필요합니다",
    ),
    "plan_approval": ReplyRules(check=_plan, from_text=_plan_text),
    "code_approval": ReplyRules(),
    "workflow_save": ReplyRules(check=_workflow),
}
