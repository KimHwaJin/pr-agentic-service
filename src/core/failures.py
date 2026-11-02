"""What users see when a turn or a report fails.

The whole exception (stack, response bodies) stays in the log under a short
error id. The user gets what went wrong in a sentence and the id; when
another service failed (the model gateway, the executor), also its own
message (addresses and secrets masked, cut short), so a model out of tokens
can be acted on without asking an operator first. Our own errors show no
detail.
"""

import logging
import re
import secrets

import httpx
import openai

from core.executor.client import ExecutorError

log = logging.getLogger(__name__)

DETAIL_MAX_CHARS = 300
_URL = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s'\"<>]+")
_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b")
_SECRET = re.compile(
    r"(?i)\b(bearer|api[_-]?key|token|password|secret)([\"':= ]+)[^\s\"',}]+"
)


def masked(text: str) -> str:
    """``text`` without addresses or secrets, on one line, cut short."""
    text = _URL.sub("[주소]", text)
    text = _IP.sub("[주소]", text)
    text = _SECRET.sub(r"\1\2***", text)
    text = " ".join(text.split())
    if len(text) > DETAIL_MAX_CHARS:
        text = text[:DETAIL_MAX_CHARS] + "…"
    return text


def _model_error(exc: openai.OpenAIError) -> tuple[str, str]:
    """(cause, detail) of a failed model call."""
    if isinstance(exc, openai.APITimeoutError):
        return "AI 모델 응답 시간이 초과되었습니다.", ""
    if isinstance(exc, openai.APIConnectionError):
        return "AI 모델 서버에 연결하지 못했습니다.", ""
    status = getattr(exc, "status_code", None)
    message = getattr(exc, "message", None) or str(exc)
    text = str(message).lower()
    if isinstance(exc, openai.RateLimitError) or status == 429:
        cause = "AI 모델 사용 한도(토큰 또는 요청 수)를 넘었습니다."
    elif status in (401, 403):
        cause = "AI 모델 호출 권한이 없습니다(키 또는 사용 한도 확인 필요)."
    elif status == 402 or "quota" in text or "budget" in text:
        cause = "AI 모델 사용 한도를 넘었습니다."
    elif "context" in text and ("length" in text or "window" in text):
        cause = "대화가 길어져 AI 모델의 입력 한도를 넘었습니다."
    elif status and status >= 500:
        cause = "AI 모델 서버에서 오류가 났습니다."
    else:
        cause = "AI 모델 호출이 거절되었습니다."
    prefix = f"HTTP {status}: " if status else ""
    return cause, prefix + str(message)


def describe(exc: BaseException) -> tuple[str, str]:
    """(cause sentence, detail text before masking) for the user."""
    if isinstance(exc, openai.OpenAIError):
        return _model_error(exc)
    if isinstance(exc, ExecutorError):
        error = exc.body.get("error") if isinstance(exc.body, dict) else None
        if isinstance(error, dict):
            code = error.get("code") or exc.status
            detail = f"{code}: {error.get('message', '')}"
        else:
            detail = f"HTTP {exc.status}"
        return (
            "분석 실행 서비스(executor)가 요청을 처리하지 못했습니다.",
            detail,
        )
    if isinstance(exc, httpx.HTTPError):
        return (
            "분석 실행 서비스와 통신하는 중 오류가 발생했습니다.",
            type(exc).__name__,
        )
    if isinstance(exc, TimeoutError):
        return "처리 시간이 초과되었습니다.", ""
    # our own bugs (SQL, stack details): the log only
    return (
        "처리 중 오류가 발생했습니다. 문제가 계속되면 오류 ID를 "
        "관리자에게 알려 주세요.",
        "",
    )


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
    cause, detail = describe(exc)
    detail = masked(detail)
    return f"{cause}{f' ({detail})' if detail else ''} 오류 ID: {error_id}"
