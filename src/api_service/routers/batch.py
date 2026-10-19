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

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request, Response

from api_service.deps import ServicesDep, UserDep
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
