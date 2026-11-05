"""What the model is told when a tool raises.

Two kinds of errors:

- errors the model can act on (a call that does not match the tool, an
  executor validation error, a ``UserFacingError``) go back word for word,
  so it can fix the call;
- every other exception is ours (the database, Redis, files, a bug). Its
  text names tables, SQL, paths and functions, which the model would quote
  to the user. The model gets only what failed, whether trying again may
  help and a reference id; the exception is logged under that id.

Unknown exceptions fall in the second kind, so a new internal error never
leaks by default.
"""

import errno
import json
import logging
import uuid
from typing import Any

import httpx
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from src.dtest.agent.plan_format import PlanFormatError
from src.dtest.core.executor.client import ExecutorError

log = logging.getLogger(__name__)

SYSTEM_ERROR = (
    "도구 실행 실패: 시스템 오류. 사용자에게는 아래 사실만 전달하세요. "
    "원인을 추측하거나 내부 구현(함수, 테이블, 경로, 오류 원문)을 언급하지 "
    "말고, 이 도구를 바로 다시 호출하지 마세요. retryable이 true면 다시 "
    "시도할지 사용자에게 물어보고, 참조 ID(ref_id)를 함께 알려 주세요."
)


class UserFacingError(Exception):
    """A tool error whose message is meant for the model and the user."""


def tool_error(exc: Exception, request: Any) -> str:
    if isinstance(exc, ExecutorError) and exc.status < 500:
        # the model may quote it to the user: the error code and message
        # only, not the whole response body
        error = exc.body.get("error") if isinstance(exc.body, dict) else None
        if isinstance(error, dict):
            detail = f"{error.get('code')}: {error.get('message', '')}"
        else:
            detail = str(exc.body)
        return f"executor 오류 {exc.status}: {detail[:500]}"
    if isinstance(exc, UserFacingError | PlanFormatError):
        return f"도구 실행 오류: {exc}"
    if isinstance(exc, TypeError) and "argument" in str(exc):
        # the call did not match the function: say what it takes
        message = f"도구 실행 오류 ({type(exc).__name__}): {exc}"
        schema = getattr(getattr(request, "tool", None), "args", None) or {}
        if schema:
            message += f"\n이 도구의 인자: {', '.join(schema)}"
        return message
    return system_error(exc, request)


def system_error(exc: Exception, request: Any) -> str:
    ref_id = uuid.uuid4().hex[:8]
    call = getattr(request, "tool_call", None) or {}
    log.error(
        "tool_system_error ref_id=%s tool=%s",
        ref_id,
        call.get("name"),
        exc_info=exc,
    )
    facts = {"error": "system", **_situation(exc), "ref_id": ref_id}
    return f"{SYSTEM_ERROR}\n{json.dumps(facts, ensure_ascii=False)}"


def _situation(exc: Exception) -> dict[str, Any]:
    """What failed, in the user's terms."""
    if isinstance(exc, ExecutorError):  # 5xx
        return {"step": "분석 실행 서버 요청", "retryable": True}
    if isinstance(exc, httpx.HTTPError):
        return {"step": "외부 서버 요청", "retryable": True}
    if isinstance(exc, SQLAlchemyError):
        return {"step": "작업 기록 저장 또는 조회", "retryable": True}
    if isinstance(exc, RedisError):
        return {"step": "실시간 상태 전달", "retryable": True}
    if isinstance(exc, TimeoutError):
        return {"step": "응답 대기(시간 초과)", "retryable": True}
    if isinstance(exc, OSError):
        if exc.errno in (errno.ENOSPC, errno.EDQUOT):
            return {
                "step": "파일 저장",
                "situation": (
                    "저장 공간이 부족합니다. 관리자 확인이 필요합니다."
                ),
                "retryable": False,
            }
        return {"step": "파일 처리", "retryable": True}
    return {"step": "요청 처리(예기치 않은 오류)", "retryable": False}
