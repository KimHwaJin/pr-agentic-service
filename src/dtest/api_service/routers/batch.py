"""pr-batch integration.

``/api/v1/batch/{path}`` relays to pr-batch ``/api/v1/{path}`` with our key
(``X-Api-Key: BATCH_API_KEY``) and the caller as ``X-User-Id``: the SSO user,
or the user a key caller names (always sent to us). pr-batch shows each
user only their own batches and scripts (404 otherwise). A master key's
reads go without ``X-User-Id``, over the tenant, its ``user_id`` query as
the filter (``deps.gateway_scope``).

Reports of finished batch runs are not asked for by pr-batch: the worker
starts one when the executor reports a successful BATCH execution (see
``worker.batch_reports``); users read them under ``/api/v1/batch-reports``.
Every call names the caller's tenant as ``X-Tenant-Id`` (ours for the
browser): pr-batch keeps scripts and batches per (tenant, user), so a
script, the batch made from it and every later read or change must name
the same tenant, and pr-batch submits a batch's runs there (their events
come to that tenant's stream). ``X-Project-Id`` is sent on registration
(``POST /batches``) only: pr-batch keeps it and never changes it.
"""

import re
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from starlette.datastructures import QueryParams

from src.dtest.api_service.deps import (
    PROJECT_ID,
    AdminDep,
    BatchScopeHeaders,
    IdentityHeaders,
    ServicesDep,
    UserDep,
    caller_of,
    current_user,
    gateway_scope,
    identity_header,
    key_identity,
    project_for,
)
from src.dtest.api_service.errors import STATUS_CODES, detail, error_response
from src.dtest.api_service.routers.artifacts import render_view
from src.dtest.api_service.schemas.batch import BatchScriptFromNotebook
from src.dtest.api_service.services.access import owned_artifact
from src.dtest.core.models import User
from src.dtest.core.service_headers import Identity, with_key
from src.dtest.core.services import Services

router = APIRouter(tags=["batch"])
FORWARD_HEADERS = ("content-type", "idempotency-key", "if-match", "accept")
_clients: dict[str, httpx.AsyncClient] = {}


def _client(services) -> httpx.AsyncClient:
    base = services.settings.batch_base_url
    if base not in _clients:
        _clients[base] = httpx.AsyncClient(base_url=base, timeout=60)
    return _clients[base]


async def close_clients() -> None:
    """On shutdown (``api_service.app.stop_api``)."""
    while _clients:
        _, client = _clients.popitem()
        await client.aclose()


def batch_headers(services: Services, who: Identity) -> dict[str, str]:
    return with_key(services.settings.batch_api_key, who)


def ours(services: Services, user_id: str) -> Identity:
    """A browser user's call: our tenant, named (see the module doc)."""
    return Identity(
        user_id=user_id, tenant=services.settings.executor_tenant_id
    )


# pr-batch's own rule for the header (its api/deps.py ``Key``)
IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=255,
        pattern=r"^[!-~]+$",
        description=(
            "A new value per registration (a UUID); the same value only "
            "to retry it. Passed to pr-batch as sent."
        ),
    ),
]
PASSED_BACK = {"etag", "location", "content-type"}


@router.post("/api/v1/batch/scripts/from-notebook", status_code=201)
async def notebook_to_batch_script(
    body: BatchScriptFromNotebook,
    services: ServicesDep,
    user: UserDep,
    idempotency_key: IdempotencyKey,
):
    """Registers a session notebook (executor artifact).

    It becomes a pr-batch NOTEBOOK script. The caller's ``Idempotency-Key``
    goes to pr-batch as sent, as on the relayed writes: a key names one
    registration, not the notebook, so registering a notebook again (after
    deleting its script, or under another name) is a new script.
    """
    artifact = await owned_artifact(services, user, body.artifact_id)
    if artifact["type"] != "NOTEBOOK":
        raise HTTPException(
            422, "Only notebook artifacts can become batch scripts."
        )
    response, chunks = await services.executor.stream_artifact(
        body.artifact_id
    )
    content = b"".join([c async for c in chunks])
    await response.aclose()
    try:
        result = await _client(services).post(
            "/api/v1/scripts",
            headers={
                **batch_headers(services, ours(services, user.id)),
                "Idempotency-Key": idempotency_key,
            },
            data={
                "type": "NOTEBOOK",
                **({"name": body.name} if body.name else {}),
            },
            files={
                "file": (
                    artifact["name"],
                    content,
                    "application/x-ipynb+json",
                )
            },
        )
    except httpx.TimeoutException:
        raise HTTPException(504, "pr-batch did not answer in time.") from None
    except httpx.HTTPError:
        raise HTTPException(502, "pr-batch is not reachable.") from None
    if result.status_code >= 400:
        return await _batch_error(result)
    return Response(
        result.content,
        result.status_code,
        headers={
            k: v for k, v in result.headers.items() if k.lower() in PASSED_BACK
        },
    )


@router.get(
    "/view/batch-scripts/{script_id}/versions/{version_id}",
    response_class=HTMLResponse,
)
async def batch_script_view(
    script_id: UUID, version_id: UUID, services: ServicesDep, user: UserDep
):
    """A script version's notebook on the artifact landing page.

    The page reads the uploaded file through the gateway; pr-batch answers
    only to the script's owner. Cells carry Step N / 건너뜀 marks.
    """
    headers = batch_headers(services, ours(services, user.id))
    client = _client(services)
    script, version = (
        await client.get(f"/api/v1/scripts/{script_id}", headers=headers),
        await client.get(
            f"/api/v1/scripts/{script_id}/versions/{version_id}",
            headers=headers,
        ),
    )
    if script.status_code == 404 or version.status_code == 404:
        raise HTTPException(404, "Script not found.")
    if script.status_code >= 400 or version.status_code >= 400:
        raise HTTPException(502, "pr-batch did not answer.")
    detail = version.json()
    return render_view(
        title=f"{script.json()['name']} · v{detail['version_number']}",
        badge="BATCH SCRIPT",
        content=(
            f"/api/v1/batch/scripts/{script_id}/versions/{version_id}/content"
        ),
        kind="notebook",
        cells=[
            {
                "index": c["index"],
                "executed": c["executed"],
                "sequence": c.get("sequence"),
            }
            for c in detail.get("cell_list", [])
        ],
    )


def registers(method: str, path: str) -> bool:
    """Batch registration (POST batches)."""
    return method == "POST" and path.strip("/") == "batches"


# The pr-batch routes callers may reach, by (method, path). Our key has
# pr-batch's admin scope (batches:disable-by-owner), so anything else,
# admin calls included, stays out. Ids are UUIDs: no "/", "." or ":" can
# ride in a segment, and httpx never sees a dot segment to resolve.
_ID = r"[0-9a-fA-F-]{36}"
_ALLOWED: list[tuple[str, str]] = [
    ("GET", r"runtimes"),
    ("GET", r"scripts"),
    ("POST", r"scripts"),
    ("GET", rf"scripts/{_ID}"),
    ("PATCH", rf"scripts/{_ID}"),
    ("DELETE", rf"scripts/{_ID}"),
    ("GET", rf"scripts/{_ID}/versions"),
    ("POST", rf"scripts/{_ID}/versions"),
    ("GET", rf"scripts/{_ID}/versions/{_ID}"),
    ("GET", rf"scripts/{_ID}/versions/{_ID}/content"),
    ("GET", r"batches"),
    ("POST", r"batches"),
    ("GET", rf"batches/{_ID}"),
    ("PATCH", rf"batches/{_ID}"),
    ("DELETE", rf"batches/{_ID}"),
    ("POST", rf"batches/{_ID}/enable"),
    ("POST", rf"batches/{_ID}/disable"),
    ("GET", rf"batches/{_ID}/skipped-windows"),
    ("GET", rf"batches/{_ID}/runs"),
    ("POST", rf"batches/{_ID}/runs"),
    ("GET", rf"batches/{_ID}/runs/{_ID}"),
    ("POST", rf"batches/{_ID}/runs/{_ID}/cancel"),
]
ROUTES = [(m, re.compile(p)) for m, p in _ALLOWED]


def relayed(method: str, path: str) -> bool:
    """Is ``path`` (already stripped of "/") a route callers may use?"""
    return any(
        method == allowed and pattern.fullmatch(path)
        for allowed, pattern in ROUTES
    )


async def gateway_identity(
    services: Services,
    request: Request,
    path: str,
    user_id: str | None,
    user: User | None,
) -> Identity:
    """Who a gateway call is made for.

    The tenant on every call: the browser's is ours, a key caller's its
    own. The project only on registration: the browser's is one the user
    belongs to; a key caller's project in another tenant is its own and
    only checked for form. ``user`` None: a key caller of another tenant,
    whose ``user_id`` is its own.
    """
    if path.strip("/") == "runtimes":  # pr-batch's own settings
        return Identity()
    caller = caller_of(request)
    our_tenant = services.settings.executor_tenant_id
    tenant = caller.tenant if caller else our_tenant
    if not registers(request.method, path):
        return Identity(user_id=user_id, tenant=tenant)
    project = identity_header(request, "x-project-id", PROJECT_ID)
    if project and tenant == our_tenant and user is not None:
        await project_for(services, user, project)
    return Identity(user_id=user_id, project_id=project, tenant=tenant)


@router.get("/api/v1/admin/users/{user_id}/batches")
async def user_batches(
    user_id: str, services: ServicesDep, admin: AdminDep, limit: int = 100
):
    """A user's batches in our tenant, as pr-batch shows them to that user
    (read only): an administrator checks that a deactivated user's batches
    went off (``disabled_reason``), which that user can no longer log in
    to see."""
    async with services.db.sessions() as db:
        if await db.get(User, user_id) is None:
            raise HTTPException(404, "User not found.")
    try:
        result = await _client(services).get(
            "/api/v1/batches",
            params={"limit": max(1, min(limit, 100))},
            headers=batch_headers(services, ours(services, user_id)),
        )
    except httpx.TimeoutException:
        raise HTTPException(504, "pr-batch did not answer in time.") from None
    except httpx.HTTPError:
        raise HTTPException(502, "pr-batch is not reachable.") from None
    if result.status_code >= 400:
        return await _batch_error(result)
    return Response(
        result.content,
        result.status_code,
        media_type=result.headers.get("content-type"),
    )


# one route per method: each gets its own OpenAPI operationId
@router.api_route("/api/v1/batch/{path:path}", methods=["GET"])
@router.api_route("/api/v1/batch/{path:path}", methods=["POST"])
@router.api_route("/api/v1/batch/{path:path}", methods=["PUT"])
@router.api_route("/api/v1/batch/{path:path}", methods=["PATCH"])
@router.api_route("/api/v1/batch/{path:path}", methods=["DELETE"])
async def batch_gateway(
    path: str,
    request: Request,
    services: ServicesDep,
    _headers: IdentityHeaders = None,
    _scope: BatchScopeHeaders = None,
):
    path = path.strip("/")
    if not relayed(request.method, path):
        raise HTTPException(404, "Not available through this service.")
    params: dict[str, str] | QueryParams = request.query_params
    if request.cookies.get(services.settings.session_cookie_name):
        user: User | None = await current_user(request)
        user_id = user.id if user else None
    else:
        caller, caller_user, user = await key_identity(
            request, services, any_user_outside=True
        )
        assert caller_user is not None
        user_id, params = gateway_scope(request, caller, caller_user)
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() in FORWARD_HEADERS
    }
    who = await gateway_identity(services, request, path, user_id, user)
    headers.update(batch_headers(services, who))
    body = await request.body()
    client = _client(services)
    outgoing = client.build_request(
        request.method,
        f"/api/v1/{path}",
        params=params,
        headers=headers,
        content=body,
    )
    try:
        # streamed: script contents and run lists can be large
        result = await client.send(outgoing, stream=True)
    except httpx.TimeoutException:
        raise HTTPException(504, "pr-batch did not answer in time.") from None
    except httpx.HTTPError:
        raise HTTPException(502, "pr-batch is not reachable.") from None
    if result.status_code >= 400:
        return await _batch_error(result)
    passthrough = {
        k: v for k, v in result.headers.items() if k.lower() in PASSED_BACK
    }

    async def chunks():
        try:
            async for chunk in result.aiter_bytes():
                yield chunk
        finally:
            await result.aclose()

    return StreamingResponse(
        chunks(), status_code=result.status_code, headers=passthrough
    )


async def _batch_error(result: httpx.Response) -> Response:
    """pr-batch's ``{code, message, errors: [{loc, type, msg}]}`` in our
    error shape (api_service.errors), so every route fails the same way."""
    try:
        await result.aread()
    finally:
        await result.aclose()
    try:
        body = result.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return error_response(
            result.status_code,
            STATUS_CODES.get(result.status_code, "error"),
            result.text[:500] or "pr-batch refused the request.",
        )
    if isinstance(body.get("error"), dict):  # already ours
        return Response(
            result.content,
            result.status_code,
            media_type="application/json",
        )
    details = [
        detail(
            list(e.get("loc") or []),
            str(e.get("type") or "invalid"),
            str(e.get("msg") or ""),
            e.get("ctx") if isinstance(e.get("ctx"), dict) else None,
        )
        for e in body.get("errors") or body.get("details") or []
        if isinstance(e, dict)
    ]
    message = body.get("message") or body.get("detail")
    if not isinstance(message, str):
        message = "pr-batch refused the request."
    code = body.get("code") or STATUS_CODES.get(result.status_code, "error")
    extra = {
        k: v
        for k, v in body.items()
        if k not in {"code", "message", "detail", "errors", "details"}
    }
    return error_response(
        result.status_code,
        str(code),
        message,
        details,
        extra or None,
    )
