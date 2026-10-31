"""Failure details stay in the log; users get a sentence and an id."""

import logging
import re

from core.executor.client import ExecutorError
from core.failures import user_message


def test_details_go_to_the_log_not_the_user(caplog):
    exc = ExecutorError(500, {"error": {"message": "http://10.0.0.5/x"}})
    with caplog.at_level(logging.ERROR):
        message = user_message(exc, "run", run_id="r1")
    error_id = re.search(r"오류 ID ([0-9a-f]{8})", message).group(1)
    assert "10.0.0.5" not in message and "ExecutorError" not in message
    assert "분석 실행 서비스" in message
    assert f"error_id={error_id}" in caplog.text and "run_id=r1" in caplog.text
    assert "10.0.0.5" in caplog.text
