"""Error responses with a machine-readable code.

Body: ``{"detail": "<human readable>", "code": "<machine code>", ...extra}``.
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
    def __init__(self, status: int, code: str, detail: str, **extra: Any):
        super().__init__(detail)
        self.status, self.code, self.detail, self.extra = (
            status,
            code,
            detail,
            extra,
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
    return JSONResponse(
        {"detail": exc.detail, "code": code},
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
    )


async def _api_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    body = {"detail": exc.detail, "code": exc.code, **exc.extra}
    return JSONResponse(_jsonable(body), status_code=exc.status)


async def _invalid_body(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [
        {
            "field": ".".join(str(p) for p in e["loc"][1:]),
            "message": e["msg"],
        }
        for e in exc.errors()
    ]
    body = {
        "detail": "Invalid request.",
        "code": "invalid_body",
        "errors": errors,
    }
    return JSONResponse(body, status_code=422)


async def _not_found(request: Request, exc: Exception) -> JSONResponse:
    # a row checked a moment ago was deleted concurrently
    return JSONResponse(
        {"detail": "Not found.", "code": "not_found"}, status_code=404
    )


async def _upstream_down(request: Request, exc: Exception) -> JSONResponse:
    # the executor or pr-batch did not answer
    log.warning("upstream_unreachable path=%s error=%r", request.url.path, exc)
    return JSONResponse(
        {"detail": "A backing service did not answer.", "code": "bad_gateway"},
        status_code=502,
    )


def _jsonable(value: Any) -> Any:
    from fastapi.encoders import jsonable_encoder

    return jsonable_encoder(value)
