"""pr-batch integration.

``/api/v1/batch/{path}`` relays to pr-batch ``/api/v1/{path}`` with our key
(``X-Api-Key: BATCH_API_KEY``) and the caller as ``X-User-Id``: the SSO user,
or the user a key caller names. pr-batch shows each user only their own
batches and scripts (404 otherwise).

Reports of finished batch runs are not asked for by pr-batch: the worker
starts one when the executor reports a successful BATCH execution (see
``worker.batch_reports``); users read them under ``/api/v1/batch-reports``.
A batch is registered (``POST /batches``) with the caller's tenant as
``X-Tenant-Id`` (ours for the browser), so pr-batch submits its runs there
and their events come to that tenant's stream; ``X-Project-Id`` is sent
then too (pr-batch keeps it and never changes it). Other calls send no
tenant: pr-batch keeps the one the batch was registered with.
"""

import hashlib
import re
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from src.dtest.api_service.deps import (
    PROJECT_ID,
    IdentityHeaders,
    ServicesDep,
    UserDep,
    caller_of,
    current_user,
    identity_header,
    key_identity,
    project_for,
)
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


def batch_headers(services: Services, who: Identity) -> dict[str, str]:
    return with_key(services.settings.batch_api_key, who)


@router.post("/api/v1/batch/scripts/from-notebook", status_code=201)
async def notebook_to_batch_script(
    body: BatchScriptFromNotebook, services: ServicesDep, user: UserDep
):
    """Registers a session notebook (executor artifact).

    It becomes a pr-batch NOTEBOOK script.
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
    digest = hashlib.sha256(content).hexdigest()[:16]
    result = await _client(services).post(
        "/api/v1/scripts",
        headers={
            **batch_headers(services, Identity(user_id=user.id)),
            "Idempotency-Key": f"nb-{body.artifact_id}-{digest}",
        },
        data={
            "type": "NOTEBOOK",
            **({"name": body.name} if body.name else {}),
        },
        files={
            "file": (artifact["name"], content, "application/x-ipynb+json")
        },
    )
    return Response(
        result.content,
        result.status_code,
        media_type=result.headers.get("content-type"),
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
    headers = batch_headers(services, Identity(user_id=user.id))
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

    The tenant and the project only on registration: the browser's tenant
    is ours and its project one the user belongs to; a key caller's project
    in another tenant is its own and only checked for form. ``user`` None:
    a key caller of another tenant, whose ``user_id`` is its own.
    """
    if path.strip("/") == "runtimes":  # pr-batch's own settings
        return Identity()
    if not registers(request.method, path):
        return Identity(user_id=user_id)
    caller = caller_of(request)
    ours = services.settings.executor_tenant_id
    tenant = caller.tenant if caller else ours
    project = identity_header(request, "x-project-id", PROJECT_ID)
    if project and tenant == ours and user is not None:
        await project_for(services, user, project)
    return Identity(user_id=user_id, project_id=project, tenant=tenant)


@router.api_route(
    "/api/v1/batch/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def batch_gateway(
    path: str,
    request: Request,
    services: ServicesDep,
    _headers: IdentityHeaders = None,
):
    path = path.strip("/")
    if not relayed(request.method, path):
        raise HTTPException(404, "Not available through this service.")
    if request.cookies.get(services.settings.session_cookie_name):
        user: User | None = await current_user(request)
        user_id = user.id if user else None
    else:
        _, user_id, user = await key_identity(
            request,
            services,
            user_required=path != "runtimes",
            any_user_outside=True,
        )
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() in FORWARD_HEADERS
    }
    who = await gateway_identity(services, request, path, user_id, user)
    headers.update(batch_headers(services, who))
    body = await request.body()
    result = await _client(services).request(
        request.method,
        f"/api/v1/{path}",
        params=request.query_params,
        headers=headers,
        content=body,
    )
    passthrough = {
        k: v
        for k, v in result.headers.items()
        if k.lower() in {"etag", "location", "content-type"}
    }
    return Response(result.content, result.status_code, headers=passthrough)
