"""Error responses with a machine-readable code.

Body: ``{"detail": "<human readable>", "code": "<machine code>", ...extra}``.
"""

import logging
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from core.db import NotFound

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


def install(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _invalid_body)
    app.add_exception_handler(NotFound, _not_found)
    app.add_exception_handler(HTTPException, _http_error)
    app.add_exception_handler(httpx.TransportError, _upstream_down)


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
