"""The executor API through this service (``/api/v1/executor/<path>``).

``/api/v1/executor/<path>`` -> executor ``/api/v1/<path>``; method, query,
body and response go through unchanged. Only the routes below are relayed,
for two kinds of caller:

- the browser (SSO): reads, checked here by project membership (admins see
  all, and may name another tenant with a ``tenant_id`` query), and the
  runtime/maintenance pages for admins (sent with the executor's operator
  key, ``EXECUTOR_ADMIN_API_KEY``);
- services and agents with one of our keys (``X-Api-Key`` + ``X-User-Id``,
  always): the executor API of their tenant, writes included, made for the
  user of ``X-User-Id``. A standard key reads only that user's executions,
  a master key the whole tenant (``deps.gateway_scope``). They never reach
  the executor directly, so this is their only way in.

The executor gets our key and identity headers made here from what we
verified, never the caller's own ``X-*`` headers.
"""

import logging
import re
from dataclasses import replace
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.dtest.api_service.deps import (
    PROJECT_ID,
    USER_ID,
    ExecutorScopeHeaders,
    IdentityHeaders,
    ServicesDep,
    current_user,
    gateway_scope,
    identity_header,
    key_identity,
    project_for,
    session_for,
)
from src.dtest.api_service.errors import ApiError
from src.dtest.api_service.services.access import (
    check_execution,
    executor_unavailable,
    scope_execution_list,
)
from src.dtest.api_service.services.api_clients import Caller
from src.dtest.core.config import RESERVED_TENANT_IDS
from src.dtest.core.executor.client import SYSTEM, Identity
from src.dtest.core.models import User
from src.dtest.core.services import Services

log = logging.getLogger(__name__)
router = APIRouter(prefix="/executor", tags=["executor"])

UUID = r"[0-9a-fA-F-]{36}"
E = rf"executions/(?P<execution>{UUID})"
# executor and pr-batch TENANT_ID_PATTERN
TENANT = re.compile(r"[a-z][a-z0-9-]{1,62}[a-z0-9]")
# what the browser may do: list / execution (membership), admin (admins),
# ops (admins, with the executor's operator key); None = not at all
Sso = Literal["list", "execution", "admin", "ops"] | None
# (method, path pattern, browser access, open to key callers)
_ALLOWED: list[tuple[str, str, Sso, bool]] = [
    ("GET", r"executions", "list", True),
    ("POST", r"executions", None, True),
    ("GET", E, "execution", True),
    ("GET", rf"{E}/result", "execution", True),
    ("GET", rf"{E}/steps", "execution", True),
    ("GET", rf"{E}/steps/{UUID}", "execution", True),
    ("GET", rf"{E}/operations", "execution", True),
    ("GET", rf"{E}/operations/{UUID}", "execution", True),
    ("GET", rf"{E}/operations/{UUID}/result", "execution", True),
    ("GET", rf"{E}/operations/{UUID}/steps", "execution", True),
    ("GET", rf"{E}/events", "execution", True),
    ("GET", rf"{E}/artifacts", "execution", True),
    ("GET", rf"{E}/notebook", "execution", True),
    ("GET", rf"{E}/notebook/cells/\d+", "execution", True),
    ("POST", rf"{E}/operations", None, True),
    ("POST", rf"{E}/finalize", None, True),
    ("POST", rf"{E}/cancel", None, True),
    ("POST", rf"{E}/retry", None, True),
    ("POST", rf"{E}/artifacts", None, True),
    ("GET", rf"artifacts/{UUID}", None, True),
    ("GET", rf"artifacts/{UUID}/content", None, True),
    # retry history and internal diagnostics: our administrators only
    ("GET", rf"{E}/attempts", "admin", False),
    ("GET", rf"{E}/attempts/{UUID}", "admin", False),
    ("GET", rf"{E}/attempts/{UUID}/steps", "admin", False),
    ("GET", rf"{E}/diagnostics", "admin", False),
    # runtime and maintenance operations: our administrators only
    ("GET", r"runtime-targets", "ops", False),
    ("GET", rf"runtime-targets/{UUID}", "ops", False),
    ("GET", r"runtime-pools", "ops", False),
    ("GET", r"maintenance", "ops", False),
    ("GET", rf"maintenance/runs/{UUID}", "ops", False),
    ("GET", rf"maintenance/runs/{UUID}/targets", "ops", False),
    # register/update (and probe), probe, take a target out of rotation and
    # back, disable, remove
    ("POST", r"runtime-targets", "ops", False),
    ("POST", rf"runtime-targets/{UUID}/probe", "ops", False),
    ("POST", rf"runtime-targets/{UUID}/drain", "ops", False),
    ("POST", rf"runtime-targets/{UUID}/activate", "ops", False),
    ("POST", rf"runtime-targets/{UUID}/disable", "ops", False),
    ("DELETE", rf"runtime-targets/{UUID}", "ops", False),
    # executor-wide admission, and stopping running executions
    ("POST", r"maintenance/drain", "ops", False),
    ("POST", r"maintenance/activate", "ops", False),
    ("POST", r"maintenance/runs", "ops", False),
]
ROUTES = [(m, re.compile(p), s, k) for m, p, s, k in _ALLOWED]


def _readable(pattern: str) -> str:
    """A route pattern as a path: ``executions/{execution_id}/steps/{id}``."""
    return (
        pattern.replace(f"(?P<execution>{UUID})", "{execution_id}")
        .replace(UUID, "{id}")
        .replace(r"\d+", "{n}")
    )


def relay_description() -> str:
    """OpenAPI text of the relay: the routes key callers may use (made from
    ``_ALLOWED``, so the docs follow the table)."""
    rows = "\n".join(
        f"| {method} | `/{_readable(pattern)}` |"
        for method, pattern, _, key in _ALLOWED
        if key
    )
    return (
        "executor `/api/v1/<path>` through this service; any other path "
        "is 404.\n\n"
        "**API key callers** (`X-Api-Key` + `X-User-Id`, always) may use "
        "the routes below. A standard key reads only the `X-User-Id` "
        "user's executions (a `user_id` query naming anyone else is 403); "
        "a master key reads the whole tenant, `user_id` narrowing it. "
        "Writes are made for `X-User-Id`:\n\n"
        "| Method | Path |\n| --- | --- |\n"
        f"{rows}\n\n"
        "Runtime, maintenance, attempts and diagnostics are for our "
        "administrators' SSO login only (the admin pages)."
    )


PASS_HEADERS = {"content-type", "etag", "location", "content-disposition"}
# scope filters we set ourselves (the caller's value is checked, not passed)
SCOPE_PARAMS = {"user_id", "tenant_id"}


# one route per method: each gets its own OpenAPI operationId
@router.api_route(
    "/{path:path}", methods=["GET"], description=relay_description()
)
@router.api_route(
    "/{path:path}", methods=["POST"], description=relay_description()
)
@router.api_route(
    "/{path:path}", methods=["DELETE"], description=relay_description()
)
async def relay(
    path: str,
    request: Request,
    services: ServicesDep,
    _headers: IdentityHeaders = None,
    _scope: ExecutorScopeHeaders = None,
):
    route = _match(request.method, path)
    cookie = services.settings.session_cookie_name
    if request.cookies.get(cookie):
        user = await current_user(request)
        if route is None or route[1] is None:
            raise HTTPException(404, "Not available through this service.")
        return await _for_user(services, request, path, route, user)
    caller, user_id, user = await key_identity(
        request, services, any_user_outside=True
    )
    assert user_id is not None
    if route is None or not route[2]:
        raise HTTPException(404, "Not available through this service.")
    return await _for_caller(services, request, path, caller, user_id, user)


async def _for_user(
    services: Services,
    request: Request,
    path: str,
    route: tuple[re.Match, Sso, bool],
    user: User,
):
    match, access, _ = route
    params = {
        k: v for k, v in request.query_params.items() if k not in SCOPE_PARAMS
    }
    # operator calls name the admin (the executor records X-User-Id)
    who = Identity(user_id=user.id) if access == "ops" else SYSTEM
    if access in {"admin", "ops"} and user.role != "admin":
        raise HTTPException(403, "Administrator only.")
    executor = services.executor
    # operator calls need the executor's operator key
    if access == "ops" and not executor.admin_api_key:
        raise ApiError(
            503,
            "executor_admin_key_missing",
            "The executor operator key (EXECUTOR_ADMIN_API_KEY) is not set.",
        )
    if access == "list" and user.role != "admin":
        await scope_execution_list(services, user, params)
        who = Identity(user_id=user.id)
    elif access == "list" and (wanted := request.query_params.get("user_id")):
        # an admin's user filter: the executor filters by X-User-Id now
        if not USER_ID.fullmatch(wanted.lower()):
            raise HTTPException(422, "user_id is malformed.")
        who = Identity(user_id=wanted.lower())
    if access == "execution" and user.role != "admin":
        await check_execution(services, user, match["execution"])
    # an admin may read another tenant's executions (our key may act for
    # every tenant); everyone else always reads ours
    wanted_tenant = request.query_params.get("tenant_id")
    if (
        wanted_tenant
        and user.role == "admin"
        and access in {"list", "execution", "admin"}
    ):
        if (
            not TENANT.fullmatch(wanted_tenant)
            or wanted_tenant in RESERVED_TENANT_IDS
        ):
            raise HTTPException(422, "tenant_id is malformed.")
        who = replace(who, tenant=wanted_tenant)
    body = await request.body() if request.method == "POST" else None
    headers = services.executor.headers(who, admin=access == "ops")
    return await _forward(
        services, request.method, path, params, body, headers
    )


async def _for_caller(
    services: Services,
    request: Request,
    path: str,
    caller: Caller,
    user_id: str,
    user: User | None,
):
    """A key caller's call, as its tenant (``gateway_scope``: whose rows a
    read covers)."""
    send_user, params = gateway_scope(request, caller, user_id)
    project = identity_header(request, "x-project-id", PROJECT_ID)
    session = request.headers.get("x-session-id", "").strip() or None
    if (
        project
        and user
        and caller.tenant == services.settings.executor_tenant_id
    ):
        # our tenant: our projects and sessions, checked as for the browser
        await project_for(services, user, project)
        if session:
            found = await session_for(services, user, session)
            if found.project_id != project:
                raise HTTPException(404, "Session not found.")
    who = Identity(
        user_id=send_user,
        project_id=project,
        session_id=session if project else None,
        tenant=caller.tenant,
    )
    body = await request.body() if request.method == "POST" else None
    headers = services.executor.headers(who)
    if body is not None and (kind := request.headers.get("content-type")):
        headers["content-type"] = kind
    response = await _forward(
        services,
        request.method,
        path,
        params,
        body,
        headers,
    )
    if request.method != "GET":
        log.info(
            "executor_gateway_write client=%s tenant=%s user=%s method=%s "
            "path=/%s status=%s",
            caller.name,
            caller.tenant,
            user_id or "",
            request.method,
            path.strip("/"),
            response.status_code,
        )
    return response


def _match(method: str, path: str) -> tuple[re.Match, Sso, bool] | None:
    path = path.strip("/")
    for allowed, pattern, sso, key in ROUTES:
        if method == allowed and (match := pattern.fullmatch(path)):
            return match, sso, key
    return None


async def _forward(
    services: Services,
    method: str,
    path: str,
    params: dict[str, str],
    body: bytes | None,
    headers: dict[str, str],
):
    http = services.executor.http
    if body and "content-type" not in headers:
        headers = {**headers, "content-type": "application/json"}
    outgoing = http.build_request(
        method,
        f"/{path.strip('/')}",
        params=params,
        content=body,
        headers=headers,
    )
    try:
        response = await http.send(outgoing, stream=True)
    except httpx.TimeoutException:
        raise ApiError(
            504, "executor_timeout", "The executor did not answer in time."
        ) from None
    except httpx.HTTPError:
        raise executor_unavailable() from None
    passed = {
        k: v for k, v in response.headers.items() if k.lower() in PASS_HEADERS
    }

    async def chunks():
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()

    return StreamingResponse(
        chunks(), status_code=response.status_code, headers=passed
    )
