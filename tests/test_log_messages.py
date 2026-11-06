"""Values are in the log message itself (2026-11-01, three services).

Inside the company network HCP's log format prints only ``%(message)s``,
and Fluent ships the printed text to Kibana: a value kept only on the
record (``extra``, ``record.request_id``) is lost there.
"""

import logging
import sys
import types
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api_service.app import audit_line
from api_service.auth.service import SsoService
from api_service.auth.store import AuthSession
from core import logging_setup
from core.config import Settings
from core.request_context import RequestIdInMessage, request_id


def _request(method="POST", path="/api/v1/projects", **state) -> Request:
    request = Request(
        {"type": "http", "method": method, "path": path, "headers": []}
    )
    for key, value in state.items():
        setattr(request.state, key, value)
    return request


def _audit(caplog, request: Request, status=200) -> list[str]:
    with caplog.at_level(logging.INFO, "api_service.audit"):
        audit_line(request, status, "dtest-agent-service")
    return [
        r.getMessage() for r in caplog.records if r.name == "api_service.audit"
    ]


def test_a_key_call_is_logged_with_the_shared_keys(caplog):
    caller = SimpleNamespace(name="pr-batch", tenant="partner")
    request = _request(
        "GET", "/api/v1/projects", api_client=caller, caller_user_id="e12345"
    )
    assert _audit(caplog, request) == [
        "api_client_request client=pr-batch tenant=partner user=e12345 "
        "method=GET path=/api/v1/projects status=200"
    ]


def test_an_sso_write_is_logged_as_client_sso_in_our_tenant(caplog):
    request = _request(
        "DELETE", "/api/v1/projects/p1", api_client=None, sso_user_id="e12345"
    )
    assert _audit(caplog, request, 204) == [
        "sso_write_request client=sso tenant=dtest-agent-service "
        "user=e12345 method=DELETE path=/api/v1/projects/p1 status=204"
    ]


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_sso_reads_are_not_logged(caplog, method):
    request = _request(method, api_client=None, sso_user_id="e12345")
    assert _audit(caplog, request) == []


def test_a_request_without_an_identity_is_not_logged(caplog):
    assert _audit(caplog, _request()) == []


class _Store:
    def __init__(self, session):
        self.session = session

    async def read_session(self, sid):
        return self.session

    async def touch(self, sid, session, ttl, cap):
        return session


def _sso(session) -> SsoService:
    return SsoService(Settings(), None, _Store(session), None)  # ty: ignore[invalid-argument-type]


async def test_sso_authentication_names_the_user_for_the_audit_line():
    session = AuthSession("e12345", "csrf", 0, 0)
    request = _request("GET")
    await _sso(session).authenticate(request)
    assert request.state.sso_user_id == "e12345"


async def test_a_write_refused_for_csrf_still_names_the_user():
    session = AuthSession("e12345", "csrf", 0, 0)
    request = _request("POST")
    with pytest.raises(HTTPException) as refused:
        await _sso(session).authenticate(request)
    assert refused.value.status_code == 403
    assert request.state.sso_user_id == "e12345"


def _record(msg="run_lease_lost run_id=%s", args=("r1",), rid="abc"):
    record = logging.LogRecord("t", logging.WARNING, "f", 1, msg, args, None)
    record.request_id = rid
    return record


def test_request_id_goes_into_the_message_once():
    record = _record()
    RequestIdInMessage().filter(record)
    RequestIdInMessage().filter(record)  # a second handler
    assert record.getMessage() == "run_lease_lost run_id=r1 request_id=abc"


def test_outside_a_request_the_message_is_left_alone():
    record = _record(rid="-")
    RequestIdInMessage().filter(record)
    assert record.getMessage() == "run_lease_lost run_id=r1"


def test_hcp_handlers_get_the_request_id_and_the_mask(monkeypatch, capsys):
    """HCP configures its own handlers; ours go on them afterwards."""
    stream = logging.StreamHandler(sys.stdout)
    # HCP's format as seen locally: the message only, no extra fields
    stream.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger = logging.getLogger("core.test_hcp_format")
    monkeypatch.setattr(logger, "handlers", [stream])
    monkeypatch.setattr(logger, "propagate", False)
    module = types.ModuleType("hcp.framework.logger")
    module.__dict__["init_logger"] = lambda: None
    monkeypatch.setitem(sys.modules, "hcp.framework.logger", module)
    logging_setup.configure_logging()
    token = request_id.set("rid-1")
    try:
        logger.warning("executor_error key=%s", "pas_live_secret123")
    finally:
        request_id.reset(token)
    assert capsys.readouterr().out == (
        "WARNING executor_error key=*** request_id=rid-1\n"
    )
