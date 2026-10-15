"""Checks a HITL answer against the question the run is waiting on.

``run.waiting`` holds the question (type, candidates, fields ...), so a wrong
answer is refused here with field-level errors instead of reaching the agent
and coming back as the same question.
"""

from typing import Any

Errors = list[dict[str, str]]


def _err(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def validate(waiting: dict[str, Any], value: Any) -> Errors:
    check = {
        "question": _question,
        "plan_approval": _plan,
        "code_approval": _approval,
        "memory_change": _approval,
        "workflow_save": _workflow,
    }.get(waiting.get("type", ""))
    return check(waiting, value) if check else []


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
    if not isinstance(value, dict):
        return [_err("value", "객체가 필요합니다")]
    action = value.get("action")
    if action == "cancel":
        return []
    if action == "revise":
        if _empty(value.get("feedback")):
            return [_err("value.feedback", "수정 요청 내용을 입력하세요")]
        return []
    if action != "approve":
        return [_err("value.action", "approve, revise, cancel 중 하나")]
    candidates = waiting.get("candidates") or []
    index = value.get("index", 0)
    if not isinstance(index, int) or not 0 <= index < len(candidates):
        return [
            _err("value.index", f"0~{len(candidates) - 1} 사이여야 합니다")
        ]
    candidate = candidates[index]
    errors: Errors = []
    inputs = value.get("input_values") or {}
    overrides = value.get("overrides") or {}
    if not isinstance(inputs, dict) or not isinstance(overrides, dict):
        return [_err("value", "input_values, overrides는 객체여야 합니다")]
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


def _approval(waiting: dict[str, Any], value: Any) -> Errors:
    if not isinstance(value, dict) or not isinstance(
        value.get("approve"), bool
    ):
        return [_err("value.approve", "true 또는 false가 필요합니다")]
    code = value.get("code")
    if code is not None and not isinstance(code, str):
        return [_err("value.code", "문자열이어야 합니다")]
    return []


def _workflow(waiting: dict[str, Any], value: Any) -> Errors:
    errors = _approval(waiting, value)
    if errors or not value["approve"]:
        return errors
    queries = value.get("user_queries")
    if queries is not None and not (
        isinstance(queries, list)
        and queries
        and all(isinstance(q, str) and q.strip() for q in queries)
    ):
        return [_err("value.user_queries", "질문 예시를 1개 이상 입력하세요")]
    return []
