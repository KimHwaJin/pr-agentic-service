"""X-Request-ID: returned on every response and on the request's log lines."""

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.executor.client import LOG_BODY_CHARS, _clip
from core.request_context import RequestId, install_log_field, request_id

seen: list[str] = []


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/x")
    async def x():
        logging.getLogger("t").warning("inside")
        seen.append(request_id.get())
        return {}

    app.add_middleware(RequestId)
    return app


def test_generated_id_is_returned_and_logged(caplog):
    install_log_field()
    client = TestClient(_app())
    with caplog.at_level(logging.WARNING, "t"):
        response = client.get("/x")
    rid = response.headers["x-request-id"]
    assert len(rid) == 32 and seen[-1] == rid
    assert [r.request_id for r in caplog.records if r.name == "t"] == [rid]
    assert request_id.get() == "-"


def test_caller_id_is_kept_when_plain():
    client = TestClient(_app())
    kept = client.get("/x", headers={"X-Request-ID": "gw-123.a"})
    assert kept.headers["x-request-id"] == "gw-123.a"
    odd = client.get("/x", headers={"X-Request-ID": "a b\tc"})
    assert odd.headers["x-request-id"] != "a b\tc"


def test_record_outside_a_request_has_a_dash():
    install_log_field()
    record = logging.getLogger("t").makeRecord("t", 20, "f", 1, "m", (), None)
    assert record.request_id == "-"


def test_executor_error_body_is_clipped_in_logs():
    assert _clip("short") == "short"
    clipped = _clip("x" * (LOG_BODY_CHARS * 3))
    assert clipped.endswith(f"({LOG_BODY_CHARS * 3} chars)")
    assert len(clipped) < LOG_BODY_CHARS + 40
