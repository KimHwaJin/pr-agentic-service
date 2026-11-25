"""The executor API through this service (``/api/v1/executor/<path>``).

``/api/v1/executor/<path>`` -> executor ``/api/v1/<path>``; method, query,
body and response go through unchanged. Only the routes below are relayed,
for two kinds of caller:

- the browser (SSO): reads, checked here by project membership (admins see
  all, and may name another tenant with a ``tenant_id`` query), and the
  runtime/maintenance/event Stream pages for admins (sent with the
  executor's operator key, ``EXECUTOR_ADMIN_API_KEY``). Its one write on
  an execution is an admin's cancel, of any tenant (``_cancel``);
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
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select

from api_service.deps import (
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
from api_service.errors import ApiError
from api_service.services.access import (
    TENANT,
    admin_tenant,
    check_execution,
    executor_unavailable,
    scope_execution_list,
)
from api_service.services.api_clients import Caller
from api_service.services.runs import request_cancel
from core.executor.client import SYSTEM, ExecutorError, Identity
from core.models import Run, User
from core.services import Services

log = logging.getLogger(__name__)
router = APIRouter(prefix="/executor", tags=["executor"])

UUID = r"[0-9a-fA-F-]{36}"
E = rf"executions/(?P<execution>{UUID})"
# a tenant's Redis event Stream; the group name goes into the executor path
# as it is, so nothing that would end the path there
STREAM = rf"event-streams/{TENANT.pattern}"
# what the browser may do: list / execution (membership), admin (admins),
# ops (admins, with the executor's operator key), cancel (admins, made
# here: ``_cancel``); None = not at all
Sso = Literal["list", "execution", "admin", "ops", "cancel"] | None
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
    # the execution's kernel, its memory and CPU now, and what its finished
    # steps recorded
    ("GET", rf"{E}/kernel-usage", "execution", True),
    ("GET", rf"{E}/notebook", "execution", True),
    ("GET", rf"{E}/notebook/cells/\d+", "execution", True),
    ("POST", rf"{E}/operations", None, True),
    ("POST", rf"{E}/finalize", None, True),
    # the browser: an administrator stops any execution (``_cancel``)
    ("POST", rf"{E}/cancel", "cancel", True),
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
    # the kernels running on a target, each with the execution that holds
    # it: every tenant's, so the operator key only
    ("GET", rf"runtime-targets/{UUID}/kernels", "ops", False),
    ("GET", r"runtime-pools", "ops", False),
    ("GET", r"maintenance", "ops", False),
    ("GET", rf"maintenance/runs/{UUID}", "ops", False),
    ("GET", rf"maintenance/runs/{UUID}/targets", "ops", False),
    # Redis event Streams as Redis holds them: our administrators only
    ("GET", r"event-streams", "ops", False),
    ("GET", STREAM, "ops", False),
    ("GET", rf"{STREAM}/entries", "ops", False),
    ("GET", rf"{STREAM}/groups/[^/?#]+/pending", "ops", False),
    # register/update (and probe), probe, take a target out of rotation and
    # back, disable, remove
    ("POST", r"runtime-targets", "ops", False),
    ("POST", rf"runtime-targets/{UUID}/probe", "ops", False),
    ("POST", rf"runtime-targets/{UUID}/drain", "ops", False),
    ("POST", rf"runtime-targets/{UUID}/activate", "ops", False),
    ("POST", rf"runtime-targets/{UUID}/disable", "ops", False),
    ("DELETE", rf"runtime-targets/{UUID}", "ops", False),
    # a kernel no execution holds (the executor refuses any other); the id
    # is Jupyter's, kept to plain characters so it cannot leave its path
    (
        "DELETE",
        rf"runtime-targets/{UUID}/kernels/[A-Za-z0-9][A-Za-z0-9_-]{{0,254}}",
        "ops",
        False,
    ),
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
        "Runtime, maintenance, event Streams, attempts and diagnostics "
        "are for our administrators' SSO login only (the admin pages)."
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
    if access == "cancel":
        return await _cancel(services, request, match["execution"], user)
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
    if user.role == "admin" and access in {"list", "execution", "admin"}:
        if tenant := admin_tenant(request.query_params.get("tenant_id")):
            who = replace(who, tenant=tenant)
    body = await request.body() if request.method == "POST" else None
    headers = services.executor.headers(who, admin=access == "ops")
    return await _forward(
        services, request.method, path, params, body, headers
    )


async def _cancel(
    services: Services, request: Request, execution_id: str, user: User
) -> JSONResponse:
    """An administrator stops an execution, whoever's and of whatever
    tenant (``tenant_id`` query; ours without it): the way to end a job
    that holds too much of a runtime.

    The executor takes a cancel only from the execution's own user, so it
    goes in that user's name; who asked is in the reason and in our log.
    The key and the reason are made here, never the browser's. A chat turn
    waiting for the execution is cancelled first: woken by a cancelled
    execution it would read a failure and could run the code again.

    Returns the executor's answer (202) with ``cancelled_run_id``; its
    errors (404, 409 for an execution already over) go back as they are.
    """
    if user.role != "admin":
        raise HTTPException(403, "Administrator only.")
    tenant = admin_tenant(request.query_params.get("tenant_id"))
    executor = services.executor
    reason = f"관리자({user.id})가 화면에서 취소"
    run_id = None
    try:
        found = await executor.get(execution_id, Identity(tenant=tenant))
        context = found.get("context") or {}
        who = Identity(
            user_id=context.get("user_id"),
            project_id=context.get("project_id"),
            session_id=context.get("session_id"),
            tenant=tenant,
        )
        # our tenant: our runs
        if tenant in (None, services.settings.executor_tenant_id):
            run_id = await _waiting_run(services, execution_id)
        if run_id:
            await request_cancel(services, run_id, reason)
        result = await executor.cancel(
            execution_id,
            who=who,
            idempotency_key=f"admin-cancel:{execution_id}",
            reason=reason,
        )
    except ExecutorError as exc:
        log.info(
            "executor_admin_cancel admin=%s tenant=%s execution_id=%s "
            "run_id=%s status=%s",
            user.id,
            tenant or "",
            execution_id,
            run_id or "",
            exc.status,
        )
        body = exc.body
        if not isinstance(body, dict):
            body = {"error": {"code": "", "message": str(body)}}
        return JSONResponse(body, status_code=exc.status)
    except httpx.TimeoutException:
        raise ApiError(
            504, "executor_timeout", "The executor did not answer in time."
        ) from None
    except httpx.HTTPError:
        raise executor_unavailable() from None
    log.info(
        "executor_admin_cancel admin=%s tenant=%s execution_id=%s owner=%s "
        "run_id=%s status=202",
        user.id,
        tenant or "",
        execution_id,
        who.user_id or "",
        run_id or "",
    )
    return JSONResponse(
        {**(result or {}), "cancelled_run_id": run_id}, status_code=202
    )


async def _waiting_run(services: Services, execution_id: str) -> str | None:
    """The chat run that waits for this execution, if one does."""
    async with services.db.sessions() as db:
        return await db.scalar(
            select(Run.id)
            .where(
                Run.status == "waiting_executor",
                Run.waiting["execution_id"].astext == execution_id,
            )
            .limit(1)
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
