"""Executor read API relayed for the frontend (BFF).

``/api/v1/executor/<path>`` -> executor ``/api/v1/<path>``, body passed
through unchanged. Only the routes below are relayed. The executor has no
user authentication, so access is checked here: executions by project
membership (admins see all), runtime and diagnostics routes for admins.
"""

import json
import re
import time
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from api_service.deps import ServicesDep, UserDep, project_for, session_for
from api_service.errors import ApiError
from core.executor.client import ExecutorError
from core.models import CodeSource, User
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
OWNER_TTL = 300.0  # an execution's project never changes
_owners: dict[str, tuple[float, str | None, str]] = {}


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
        await _scope_list(services, user, params)
    if access == "execution" and user.role != "admin":
        await _check_execution(services, user, match["execution"])
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
        data["actor"] = {"type": "USER", "id": user.employee_id}
    return json.dumps(data).encode()


def _match(method: str, path: str) -> tuple[Access, re.Match] | None:
    path = path.strip("/")
    for allowed, pattern, access in ROUTES:
        if method == allowed and (match := pattern.fullmatch(path)):
            return access, match
    return None


async def _scope_list(
    services: Services, user: User, params: dict[str, str]
) -> None:
    """Only the caller's executions, inside projects they belong to."""
    if session_id := params.get("session_id"):
        session = await session_for(services, user, session_id)
        params["project_id"] = session.project_id
    elif project_id := params.get("project_id"):
        await project_for(services, user, project_id)
    params["user_id"] = user.employee_id


async def _check_execution(
    services: Services, user: User, execution_id: str
) -> None:
    project_id, owner = await _owner(services, execution_id)
    if project_id is not None:
        await project_for(services, user, project_id)  # 404 when not a member
    elif owner != user.employee_id:
        raise HTTPException(404, "Execution not found.")


async def _owner(
    services: Services, execution_id: str
) -> tuple[str | None, str]:
    """(project id, employee id) of an execution, cached."""
    hit = _owners.get(execution_id)
    if hit and hit[0] > time.monotonic():
        return hit[1], hit[2]
    async with services.db.sessions() as db:
        row = (
            await db.execute(
                select(CodeSource.project_id, User.employee_id)
                .join(User, User.id == CodeSource.user_id)
                .where(CodeSource.execution_id == execution_id)
                .limit(1)
            )
        ).first()
    if row is not None:
        owner = (row.project_id, row.employee_id)
    else:  # not sent by this service (e.g. pr-batch): ask the executor
        try:
            execution = await services.executor.get(execution_id)
        except ExecutorError as exc:
            if exc.status == 404:
                raise HTTPException(404, "Execution not found.") from None
            raise _unavailable() from None
        except httpx.HTTPError:
            raise _unavailable() from None
        context = execution.get("context") or {}
        owner = (context.get("project_id"), context.get("user_id", ""))
    _owners[execution_id] = (time.monotonic() + OWNER_TTL, *owner)
    if len(_owners) > 10000:
        _owners.clear()
    return owner


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
        raise _unavailable() from None
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


def _unavailable() -> ApiError:
    return ApiError(
        502, "executor_unavailable", "The executor did not answer."
    )
