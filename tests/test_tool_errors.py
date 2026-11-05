import errno
import json
import logging

from sqlalchemy.exc import DataError

from src.dtest.agent.plan_format import PlanFormatError
from src.dtest.agent.tool_errors import (
    SYSTEM_ERROR,
    UserFacingError,
    tool_error,
)
from src.dtest.core.executor.client import ExecutorError


class _Request:
    tool_call = {"name": "run_plan", "id": "c1", "args": {}}
    tool = None


def _facts(message: str) -> dict:
    head, facts = message.split("\n", 1)
    assert head == SYSTEM_ERROR
    return json.loads(facts)


def test_a_database_error_reaches_the_model_without_its_text(caplog):
    # the NaN case: Postgres refused the run_events insert
    exc = DataError(
        "INSERT INTO run_events (session_id, run_id, type, data) VALUES ...",
        {},
        Exception('invalid input syntax for type json: Token "NaN"'),
    )
    with caplog.at_level(logging.ERROR):
        message = tool_error(exc, _Request())
    assert "run_events" not in message and "NaN" not in message
    facts = _facts(message)
    assert facts["step"] == "작업 기록 저장 또는 조회"
    assert facts["retryable"] is True
    # the log has the whole exception under the same reference id
    record = caplog.records[-1]
    assert facts["ref_id"] in record.getMessage() and record.exc_info


def test_unknown_errors_are_hidden_by_default():
    message = tool_error(KeyError("plan_internal_key"), _Request())
    assert "plan_internal_key" not in message
    assert _facts(message)["retryable"] is False


def test_a_full_disk_says_so_without_the_path():
    exc = OSError(errno.ENOSPC, "No space left", "/shared/runs/01/x.tmp")
    message = tool_error(exc, _Request())
    assert "/shared" not in message
    assert "저장 공간" in _facts(message)["situation"]


def test_errors_the_model_can_fix_keep_their_text():
    assert "bad value" in tool_error(UserFacingError("bad value"), _Request())
    assert "#3 없음" in tool_error(PlanFormatError("#3 없음"), _Request())
    exc = ExecutorError(422, {"error": {"code": "BAD", "message": "no col"}})
    assert tool_error(exc, _Request()) == "executor 오류 422: BAD: no col"


def test_an_executor_outage_is_a_system_error():
    exc = ExecutorError(503, {"error": {"code": "DOWN", "message": "pod x"}})
    message = tool_error(exc, _Request())
    assert "pod x" not in message
    assert _facts(message)["step"] == "분석 실행 서버 요청"
