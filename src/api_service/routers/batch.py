"""pr-batch integration.

``/api/v1/batch/{path}`` relays to pr-batch ``/api/v1/{path}`` with a
short-lived JWT for the SSO user (HS256, aud=pr-batch, sub=users.id,
scope=batch:manage, <= 300 s).

Reports of finished batch runs are not asked for by pr-batch: the worker
starts one when the executor reports a successful BATCH execution (see
``worker.batch_reports``); users read them under ``/api/v1/batch-reports``.
"""

import hashlib
import time
from uuid import UUID

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from api_service.deps import ServicesDep, UserDep
from api_service.routers.artifacts import render_view
from api_service.schemas.batch import BatchScriptFromNotebook
from api_service.services.access import owned_artifact

router = APIRouter(tags=["batch"])
FORWARD_HEADERS = ("content-type", "idempotency-key", "if-match", "accept")
_clients: dict[str, httpx.AsyncClient] = {}


def _client(services) -> httpx.AsyncClient:
    base = services.settings.batch_base_url
    if base not in _clients:
        _clients[base] = httpx.AsyncClient(base_url=base, timeout=60)
    return _clients[base]


def _batch_token(services, user) -> str:
    settings = services.settings
    if not settings.batch_jwt_secret:
        raise HTTPException(503, "pr-batch integration is not configured.")
    now = int(time.time())
    claims = {
        "sub": user.id,
        "iss": settings.batch_jwt_issuer,
        "aud": "pr-batch",
        "iat": now,
        "exp": now + 300,
        "scope": "batch:manage",
    }
    return jwt.encode(claims, settings.batch_jwt_secret, algorithm="HS256")


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
            "Authorization": f"Bearer {_batch_token(services, user)}",
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
    headers = {"Authorization": f"Bearer {_batch_token(services, user)}"}
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


@router.api_route(
    "/api/v1/batch/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def batch_gateway(
    path: str, request: Request, services: ServicesDep, user: UserDep
):
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() in FORWARD_HEADERS
    }
    headers["Authorization"] = f"Bearer {_batch_token(services, user)}"
    result = await _client(services).request(
        request.method,
        f"/api/v1/{path}",
        params=request.query_params,
        headers=headers,
        content=await request.body(),
    )
    passthrough = {
        k: v
        for k, v in result.headers.items()
        if k.lower() in {"etag", "location", "content-type"}
    }
    return Response(result.content, result.status_code, headers=passthrough)
