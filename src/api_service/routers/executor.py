"""Executor read API relayed for the frontend (BFF).

``/api/v1/executor/<path>`` -> executor ``/api/v1/<path>``, body passed
through unchanged. Only the routes below are relayed. The executor has no
user authentication, so access is checked here: executions by project
membership (admins see all), runtime and diagnostics routes for admins.
"""

import json
import re
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from api_service.deps import ServicesDep, UserDep
from api_service.services.access import (
    check_execution,
    executor_unavailable,
    scope_execution_list,
)
from core.models import User
from core.services import Services

router = APIRouter(prefix="/executor", tags=["executor"])

UUID = r"[0-9a-fA-F-]{36}"
Access = Literal["list", "execution", "admin"]
# (method, path pattern, access)
_ALLOWED: list[tuple[str, str, Access]] = [
    ("GET", r"executions", "list"),
    ("GET", rf"executions/(?P<execution>{UUID})", "execution"),
    ("GET", rf"executions/(?P<execution>{UUID})/result", "execution"),
    ("GET", rf"executions/(?P<execution>{UUID})/steps", "execution"),
    (
        "GET",
        rf"executions/(?P<execution>{UUID})/steps/{UUID}",
        "execution",
    ),
    ("GET", rf"executions/(?P<execution>{UUID})/events", "execution"),
    ("GET", rf"executions/(?P<execution>{UUID})/artifacts", "execution"),
    ("GET", rf"executions/(?P<execution>{UUID})/notebook", "execution"),
    # operations and diagnostics: administrators
    ("GET", rf"executions/{UUID}/diagnostics", "admin"),
    ("GET", rf"executions/{UUID}/attempts", "admin"),
    ("GET", rf"executions/{UUID}/attempts/{UUID}", "admin"),
    ("GET", rf"executions/{UUID}/attempts/{UUID}/steps", "admin"),
    ("GET", r"runtime-targets", "admin"),
    ("GET", rf"runtime-targets/{UUID}", "admin"),
    ("GET", r"runtime-pools", "admin"),
    ("GET", r"maintenance", "admin"),
    ("GET", rf"maintenance/runs/{UUID}", "admin"),
    ("GET", rf"maintenance/runs/{UUID}/targets", "admin"),
    # runtime operations: register/update (and probe), probe, take a target
    # out of rotation and back, disable, remove
    ("POST", r"runtime-targets", "admin"),
    ("POST", rf"runtime-targets/{UUID}/probe", "admin"),
    ("POST", rf"runtime-targets/{UUID}/drain", "admin"),
    ("POST", rf"runtime-targets/{UUID}/activate", "admin"),
    ("POST", rf"runtime-targets/{UUID}/disable", "admin"),
    ("POST", rf"runtime-targets/{UUID}/purge", "admin"),
    # executor-wide admission, and stopping running executions
    ("POST", r"maintenance/drain", "admin"),
    ("POST", r"maintenance/activate", "admin"),
    ("POST", r"maintenance/runs", "admin"),
]
ROUTES = [(m, re.compile(p), a) for m, p, a in _ALLOWED]
PASS_HEADERS = {"content-type", "etag", "location", "content-disposition"}


@router.api_route("/{path:path}", methods=["GET", "POST"])
async def relay(
    path: str, request: Request, services: ServicesDep, user: UserDep
):
    route = _match(request.method, path)
    if route is None:
        raise HTTPException(404, "Not available through this service.")
    access, match = route
    params = dict(request.query_params)
    if access == "admin" and user.role != "admin":
        raise HTTPException(403, "Administrator only.")
    if access == "list" and user.role != "admin":
        await scope_execution_list(services, user, params)
    if access == "execution" and user.role != "admin":
        await check_execution(services, user, match["execution"])
    body = await request.body() if request.method == "POST" else None
    if body is not None:
        body = _as_user(body, user)
    return await _forward(services, request.method, path, params, body)


def _as_user(body: bytes, user: User) -> bytes:
    """Mutations are recorded as done by this user, not by the client."""
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        return body  # the executor answers with its validation error
    if isinstance(data, dict):
        data["actor"] = {"type": "USER", "id": user.id}
    return json.dumps(data).encode()


def _match(method: str, path: str) -> tuple[Access, re.Match] | None:
    path = path.strip("/")
    for allowed, pattern, access in ROUTES:
        if method == allowed and (match := pattern.fullmatch(path)):
            return access, match
    return None


async def _forward(
    services: Services,
    method: str,
    path: str,
    params: dict[str, str],
    body: bytes | None,
):
    http = services.executor.http
    outgoing = http.build_request(
        method,
        f"/{path.strip('/')}",
        params=params,
        content=body,
        headers={"content-type": "application/json"} if body else None,
    )
    try:
        response = await http.send(outgoing, stream=True)
    except httpx.HTTPError:
        raise executor_unavailable() from None
    headers = {
        k: v for k, v in response.headers.items() if k.lower() in PASS_HEADERS
    }
    if response.status_code == 404:
        await response.aclose()
        raise HTTPException(404, "Not found.")

    async def body():
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()

    return StreamingResponse(
        body(), status_code=response.status_code, headers=headers
    )
