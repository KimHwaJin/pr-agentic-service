"""What the bridge answers on its own when a run asks for a confirmation.

gaia's own HITL is not wired up, so approvals are given here (the first
plan candidate, the code as written) and offers to save memory or a
workflow are declined. A question for the user, and a plan that still
needs values, end the gaia turn with the question as the answer; the next
gaia message answers it (a message typed while a question is pending is
its answer, as in our chat API).
"""

from typing import Any

Waiting = dict[str, Any]


def reply(waiting: Waiting) -> Any | None:
    """The resume value, or None when only the user can answer."""
    kind = waiting.get("type")
    if kind == "plan_approval":
        candidates = waiting.get("candidates") or []
        if not candidates or _missing(candidates[0]):
            return None
        return {"action": "approve", "index": 0}
    if kind == "code_approval":
        return {"approve": True}
    if kind in {"memory_change", "workflow_save"}:
        return {"approve": False}
    return None


def ask(waiting: Waiting) -> str:
    """The question shown as the turn's answer."""
    kind = waiting.get("type")
    if kind == "question":
        lines = [waiting.get("question") or "추가 정보가 필요합니다."]
        lines += [f"- {option}" for option in waiting.get("options") or []]
        fields = waiting.get("fields") or []
        if len(fields) > 1:
            lines.append("")
            lines += [f"- {f.get('label') or f['key']}" for f in fields]
        return "\n".join(lines)
    if kind == "plan_approval":
        candidates = waiting.get("candidates") or []
        if candidates:
            first = candidates[0]
            needed = ", ".join(_missing(first))
            return (
                f"'{first.get('title', '분석 계획')}' 계획을 실행하려면 "
                f"다음 값이 필요합니다: {needed}\n값을 알려 주세요."
            )
    return "진행하려면 확인이 필요합니다. 어떻게 할지 알려 주세요."


def _missing(candidate: dict[str, Any]) -> list[str]:
    given = candidate.get("input_values") or {}
    return [
        slot["key"]
        for slot in candidate.get("input_slots") or []
        if slot.get("required")
        and slot.get("value") is None
        and given.get(slot["key"]) is None
    ]
