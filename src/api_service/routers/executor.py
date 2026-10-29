"""The executor API through this service (``/api/v1/executor/<path>``).

``/api/v1/executor/<path>`` -> executor ``/api/v1/<path>``; method, query,
body and response go through unchanged. Only the routes below are relayed,
for two kinds of caller:

- the browser (SSO): reads, checked here by project membership (admins see
  all), and the runtime/maintenance pages for admins (sent with the
  executor's operator key, ``EXECUTOR_ADMIN_API_KEY``);
- services and agents with one of our keys (``X-Api-Key``): the executor
  API of their tenant, writes included, as the user of ``X-User-Id``. They
  never reach the executor directly, so this is their only way in.

The executor gets our key and identity headers made here from what we
verified, never the caller's own ``X-*`` headers.
"""

import json
import logging
import re
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from api_service.deps import (
    PROJECT_ID,
    USER_ID,
    IdentityHeaders,
    ServicesDep,
    current_user,
    identity_header,
    key_identity,
    project_for,
    session_for,
)
from api_service.errors import ApiError
from api_service.services.access import (
    check_execution,
    executor_unavailable,
    scope_execution_list,
)
from api_service.services.api_clients import Caller
from core.executor.client import SYSTEM, Identity
from core.models import User
from core.services import Services

log = logging.getLogger(__name__)
router = APIRouter(prefix="/executor", tags=["executor"])

UUID = r"[0-9a-fA-F-]{36}"
E = rf"executions/(?P<execution>{UUID})"
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
    ("GET", rf"{E}/attempts", "admin", True),
    ("GET", rf"{E}/attempts/{UUID}", "admin", True),
    ("GET", rf"{E}/attempts/{UUID}/steps", "admin", True),
    # internal diagnostics: our administrators only
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
    ("POST", rf"runtime-targets/{UUID}/purge", "ops", False),
    # executor-wide admission, and stopping running executions
    ("POST", r"maintenance/drain", "ops", False),
    ("POST", r"maintenance/activate", "ops", False),
    ("POST", r"maintenance/runs", "ops", False),
]
ROUTES = [(m, re.compile(p), s, k) for m, p, s, k in _ALLOWED]
PASS_HEADERS = {"content-type", "etag", "location", "content-disposition"}
# list filters the executor no longer takes: the headers decide the scope
SCOPE_PARAMS = {"user_id", "tenant_id"}


@router.api_route("/{path:path}", methods=["GET", "POST"])
async def relay(
    path: str,
    request: Request,
    services: ServicesDep,
    _headers: IdentityHeaders = None,
):
    route = _match(request.method, path)
    cookie = services.settings.session_cookie_name
    if request.cookies.get(cookie):
        user = await current_user(request)
        if route is None or route[1] is None:
            raise HTTPException(404, "Not available through this service.")
        return await _for_user(services, request, path, route, user)
    caller, user = await key_identity(
        request, services, user_required=request.method != "GET"
    )
    if route is None or not route[2]:
        raise HTTPException(404, "Not available through this service.")
    return await _for_caller(services, request, path, caller, user)


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
    # operator calls name the admin (the executor matches a USER actor)
    who = Identity(user_id=user.id) if access == "ops" else SYSTEM
    if access in {"admin", "ops"} and user.role != "admin":
        raise HTTPException(403, "Administrator only.")
    executor = services.executor
    # no key at all: an executor in header mode, where that is an operator
    if access == "ops" and executor.api_key and not executor.admin_api_key:
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
    body = await request.body() if request.method == "POST" else None
    if body is not None:
        body = _as_user(body, user)
    headers = services.executor.headers(who, admin=access == "ops")
    return await _forward(
        services, request.method, path, params, body, headers
    )


async def _for_caller(
    services: Services,
    request: Request,
    path: str,
    caller: Caller,
    user: User | None,
):
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
        user_id=user.id if user else None,
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
        dict(request.query_params),
        body,
        headers,
    )
    if request.method != "GET":
        log.info(
            "executor_gateway_write client=%s tenant=%s user=%s method=%s "
            "path=/%s status=%s",
            caller.name,
            caller.tenant,
            user.id if user else "",
            request.method,
            path.strip("/"),
            response.status_code,
        )
    return response


def _as_user(body: bytes, user: User) -> bytes:
    """Mutations are recorded as done by this user, not by the client."""
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        return body  # the executor answers with its validation error
    if isinstance(data, dict):
        data["actor"] = {"type": "USER", "id": user.id}
    return json.dumps(data).encode()


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
