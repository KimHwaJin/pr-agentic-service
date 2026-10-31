"""What users see when a turn or a report fails.

The exception text (executor response bodies, internal URLs, SQL) stays
in the log under a short error id; the user gets a plain sentence with
that id to quote to an operator.
"""

import logging
import secrets

import httpx

from src.dtest.core.executor.client import ExecutorError

log = logging.getLogger(__name__)


def user_message(exc: BaseException, what: str, **context: str) -> str:
    """Logs ``exc`` with a new error id and returns the user's message."""
    error_id = secrets.token_hex(4)
    log.error(
        "%s_failed error_id=%s %s",
        what,
        error_id,
        " ".join(f"{k}={v}" for k, v in context.items()),
        exc_info=exc,
    )
    if isinstance(exc, ExecutorError | httpx.HTTPError):
        cause = "분석 실행 서비스와 통신하는 중 오류가 발생했습니다."
    elif isinstance(exc, TimeoutError):
        cause = "처리 시간이 초과되었습니다."
    else:
        cause = "처리 중 오류가 발생했습니다."
    return (
        f"{cause} 문제가 계속되면 오류 ID {error_id}를 관리자에게 알려 주세요."
    )
