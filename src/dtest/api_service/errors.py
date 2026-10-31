"""Error responses, one shape for every route (same as the executor's)::

    {"error": {"code": "<machine code>", "message": "<human readable>",
               "details": [{"location": [...], "type": "...",
                            "message": "...", "context": {...}}],
               "context": {...}}}

``details``: one entry per offending value (where, why, the values the
check used); empty when the error is about the request as a whole.
``context``: facts about the error that are not tied to one value (the
active run of a busy session, the models to choose from); left out when
there are none.
"""

import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi import HTTPException as FastAPIHTTPException
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from src.dtest.api_service import API_PREFIX
from src.dtest.core.db import NotFound

log = logging.getLogger(__name__)

# code for plain HTTPExceptions raised without one
STATUS_CODES = {
    400: "bad_request",
    401: "login_required",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    413: "too_large",
    422: "invalid_body",
    502: "bad_gateway",
}


class ApiError(Exception):
    """``details``: entries made with ``detail``; ``context``: the rest."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
        **context: Any,
    ):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.details, self.context = details or [], context


def detail(
    location: list[str | int] | str,
    type: str,
    message: str = "",
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One ``details`` entry; a dotted ``location`` is split."""
    if isinstance(location, str):
        location = [int(p) if p.isdigit() else p for p in location.split(".")]
    return {
        "location": location,
        "type": type,
        "message": message,
        "context": context or {},
    }


def error_body(
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "details": details or [],
    }
    if context:
        error["context"] = context
    return {"error": error}


def error_response(
    status: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    context: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        _jsonable(error_body(code, message, details, context)),
        status_code=status,
        headers=headers,
    )


# Our routes. The app is shared with the gaia template's own APIs, whose
# errors keep the handler they had before ours (or FastAPI's default).
OWN_PREFIXES = (API_PREFIX + "/", "/view/", "/dev/")

Handler = Callable[[Request, Exception], Response | Awaitable[Response]]


def install(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(NotFound, _not_found)
    handlers = app.exception_handlers
    starlette_http = handlers.get(HTTPException, http_exception_handler)
    for cls, handler, previous in (
        (
            RequestValidationError,
            _invalid_body,
            handlers.get(RequestValidationError, _invalid_body_default),
        ),
        (HTTPException, _http_error, starlette_http),
        # FastAPI's subclass, in case the app registered a handler for it
        (
            FastAPIHTTPException,
            _http_error,
            handlers.get(FastAPIHTTPException, starlette_http),
        ),
        (httpx.TransportError, _upstream_down, _reraise),
    ):
        app.add_exception_handler(cls, _scoped(handler, previous))


def _scoped(own: Handler, other: Handler) -> Handler:
    async def handle(request: Request, exc: Exception) -> Response:
        path = request.url.path
        mine = path.startswith(OWN_PREFIXES) or path + "/" in OWN_PREFIXES
        response = (own if mine else other)(request, exc)
        return await response if inspect.isawaitable(response) else response

    return handle


async def _invalid_body_default(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, RequestValidationError)
    return await request_validation_exception_handler(request, exc)


async def _reraise(request: Request, exc: Exception) -> Response:
    raise exc


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HTTPException)
    code = STATUS_CODES.get(exc.status_code, "error")
    return error_response(
        exc.status_code,
        code,
        str(exc.detail),
        headers=getattr(exc, "headers", None),
    )


async def _api_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return error_response(
        exc.status, exc.code, exc.message, exc.details, exc.context
    )


async def _invalid_body(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # the offending values themselves are not echoed (base64 images, keys)
    details = [
        detail(list(e["loc"]), e["type"], e["msg"], dict(e.get("ctx") or {}))
        for e in exc.errors()
    ]
    return error_response(422, "invalid_body", "Invalid request.", details)


async def _not_found(request: Request, exc: Exception) -> JSONResponse:
    # a row checked a moment ago was deleted concurrently
    return error_response(404, "not_found", "Not found.")


async def _upstream_down(request: Request, exc: Exception) -> JSONResponse:
    # the executor or pr-batch did not answer
    log.warning("upstream_unreachable path=%s error=%r", request.url.path, exc)
    return error_response(
        502, "bad_gateway", "A backing service did not answer."
    )


def _jsonable(value: Any) -> Any:
    from fastapi.encoders import jsonable_encoder

    # ctx can hold exceptions (pydantic value_error): written as text
    return jsonable_encoder(value, custom_encoder={Exception: str})
