"""What a tool call is doing, in a short Korean line for the screen.

Sent as ``label`` on the ``tool_call`` event, so a client shows progress
without its own table of tool names. Unknown tools show their name.
"""

from collections.abc import Callable
from typing import Any

Args = dict[str, Any]


def _join(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return "" if value is None else str(value)


LABELS: dict[str, Callable[[Args], str]] = {
    # main agent
    "read_knowledge": lambda a: f"도메인 지식 확인 · {_join(a.get('name'))}",
    "save_memory": lambda a: f"메모리 저장 · {_join(a.get('topic'))}",
    "delete_memory": lambda a: "메모리 삭제",
    "start_analysis": lambda a: "분석 담당에게 전달",
    # analyst
    "read_skill": lambda a: f"분석 skill 확인 · {_join(a.get('name'))}",
    "read_tool": lambda a: (
        "도구 확인 · " + _join(a.get("names") or a.get("name"))
    ),
    "search_tools": lambda a: "도구 검색",
    "search_workflows": lambda a: "등록된 워크플로우 검색",
    "propose_plans": lambda a: "실행 계획 작성",
    "revise_call": lambda a: f"파라미터 수정 · #{_join(a.get('call'))}",
    "run_plan": lambda a: (
        "조건 판단 후 이어서 실행" if a.get("decisions") else "코드 실행 요청"
    ),
    "run_custom_code": lambda a: (
        "직접 작성한 코드 실행 · " + _join(a.get("purpose"))
    ),
    "write_report": lambda a: "리포트·노트북 확정",
    "save_workflow": lambda a: "워크플로우 저장 제안",
    "finish_analysis": lambda a: "분석 정리",
    # batch report agent
    "read_step": lambda a: f"Step {_join(a.get('sequence'))} 결과 확인",
    "submit_report": lambda a: "리포트 제출",
}


def tool_label(name: str, args: Args) -> str:
    make = LABELS.get(name)
    if make is None:
        return name
    try:
        return make(args or {}).rstrip(" ·")
    except Exception:  # noqa: BLE001 - a label never breaks a turn
        return name
