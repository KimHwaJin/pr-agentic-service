"""Request id: one id per HTTP request, on every log line it causes.

The id comes from the caller's ``X-Request-ID`` (an ingress or gateway
usually sets one) or is made here, is sent back in the response header,
and is passed on to the executor so one request can be followed across
services. Log records carry it as ``record.request_id`` ("-" outside a
request), and ``RequestIdInMessage`` writes it into the message as
``request_id=<id>``: the platform's log format (HCP) prints only the
message, so a record attribute alone would not reach Kibana.
"""

import logging
import re
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADER = "X-Request-ID"
_HEADER = HEADER.lower().encode()
# a caller's id is kept only when it is short and plain (it lands in logs)
_VALID = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")
request_id: ContextVar[str] = ContextVar("request_id", default="-")


def install_log_field() -> None:
    """Every log record gets ``request_id``, whatever handler writes it."""
    previous = logging.getLogRecordFactory()
    if getattr(previous, "_adds_request_id", False):
        return

    def factory(*args, **kwargs) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        record.request_id = request_id.get()
        return record

    factory._adds_request_id = True  # ty: ignore[unresolved-attribute]
    logging.setLogRecordFactory(factory)


class RequestIdInMessage(logging.Filter):
    """Ends a request's log messages with `` request_id=<id>``.

    On handlers (``core.logging_setup``); a record two handlers write gets
    the id once.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        rid = getattr(record, "request_id", "-")
        if rid != "-" and not getattr(record, "request_id_in_message", False):
            record.msg, record.args = (
                f"{record.getMessage()} request_id={rid}",
                None,
            )
            record.request_id_in_message = True
        return True


class RequestId:
    """ASGI middleware: sets the id for the request and returns it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        given = (
            dict(scope.get("headers") or [])
            .get(_HEADER, b"")
            .decode("latin-1")
        )
        rid = given if _VALID.match(given) else uuid.uuid4().hex
        token = request_id.set(rid)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() != _HEADER
                ]
                headers.append((_HEADER, rid.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id.reset(token)
