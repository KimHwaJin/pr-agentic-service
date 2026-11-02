"""Failure details stay in the log; users get a sentence and an id."""

import logging
import re

from src.dtest.core.executor.client import ExecutorError
from src.dtest.core.failures import user_message


def test_details_go_to_the_log_not_the_user(caplog):
    exc = ExecutorError(500, {"error": {"message": "http://10.0.0.5/x"}})
    with caplog.at_level(logging.ERROR):
        message = user_message(exc, "run", run_id="r1")
    error_id = re.search(r"오류 ID: ([0-9a-f]{8})", message).group(1)
    assert "10.0.0.5" not in message and "ExecutorError" not in message
    assert "분석 실행 서비스" in message and "500" in message
    assert f"error_id={error_id}" in caplog.text and "run_id=r1" in caplog.text
    assert "10.0.0.5" in caplog.text


def _status_error(cls, status, message):
    import httpx

    request = httpx.Request("POST", "http://10.1.2.3:8000/v1/chat/completions")
    response = httpx.Response(status, request=request)
    return cls(message, response=response, body={"message": message})


def test_a_model_out_of_tokens_says_so():
    import openai

    exc = _status_error(
        openai.RateLimitError,
        429,
        "TPM limit exceeded for key sk-abc at http://10.1.2.3:8000/v1",
    )
    message = user_message(exc, "run")
    assert "사용 한도" in message and "HTTP 429" in message
    assert "TPM limit exceeded" in message
    assert "10.1.2.3" not in message and "http://" not in message
    assert re.search(r"오류 ID: [0-9a-f]{8}", message)


def test_a_too_long_conversation_says_so():
    import openai

    exc = _status_error(
        openai.BadRequestError,
        400,
        "This model's maximum context length is 32768 tokens",
    )
    assert "입력 한도" in user_message(exc, "run")


def test_executor_errors_show_their_code_without_addresses():
    exc = ExecutorError(
        409, {"error": {"code": "TENANT_DISABLED", "message": "at http://x/y"}}
    )
    message = user_message(exc, "run")
    assert "TENANT_DISABLED" in message and "http://" not in message


def test_our_own_errors_show_no_detail():
    message = user_message(KeyError("select * from users"), "run")
    assert "select" not in message and "KeyError" not in message
