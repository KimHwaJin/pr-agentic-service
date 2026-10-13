"""pr-batch integration.

* Gateway: ``/api/v1/batch/{path}`` relays to pr-batch ``/api/v1/{path}``
  with a short-lived JWT for the SSO user (HS256, aud=pr-batch,
  scope=batch:manage, <= 300 s).
* ``/internal/v1/execution-reports``: pr-batch asks for a report of a
  finished batch execution, authenticated with its own service token
  (iss=pr-batch, aud=prj_re-report).
"""

import hashlib
import json
import time
import uuid

import httpx
import jwt
from fastapi import APIRouter, Header, HTTPException, Request, Response
from sqlalchemy import select

from api_service.deps import ServicesDep, UserDep
from api_service.routers.artifacts import _owned_artifact
from api_service.schemas import BatchScriptFromNotebook, ReportJobCreate
from core.models import BatchReportJob

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
        "sub": user.employee_id,
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
    artifact = await _owned_artifact(services, user, body.artifact_id)
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


# --- called by pr-batch -----------------------------------------------------


def _verify_service_token(services, authorization: str | None) -> dict:
    secret = services.settings.batch_report_jwt_secret
    if (
        not secret
        or not authorization
        or not authorization.startswith("Bearer ")
    ):
        raise HTTPException(401, "Service token required.")
    try:
        return jwt.decode(
            authorization[7:],
            secret,
            algorithms=["HS256"],
            audience="prj_re-report",
            issuer="pr-batch",
            options={"require": ["exp", "iat", "iss", "aud"]},
        )
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid service token.") from None


def _job_view(job: BatchReportJob) -> dict:
    return {
        "report_job_id": job.id,
        "state": job.state,
        "failed_stage": job.failed_stage,
        "execution_id": job.execution_id,
        "batch_run_id": job.batch_run_id,
        "artifact_id": job.artifact_id,
        "notebook_appended": job.state == "SUCCEEDED",
        "error": job.error,
        "updated_at": job.updated_at,
    }


@router.post("/internal/v1/execution-reports", status_code=202)
async def create_report_job(
    body: ReportJobCreate,
    services: ServicesDep,
    authorization: str | None = Header(None),
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
):
    claims = _verify_service_token(services, authorization)
    if claims.get("owner_id", body.owner_id) != body.owner_id:
        raise HTTPException(403, "Token owner does not match the request.")
    execution = await services.executor.get(body.execution_id)
    if execution["context"]["user_id"] != body.owner_id:
        raise HTTPException(403, "The execution belongs to another user.")
    digest = hashlib.sha256(
        json.dumps(body.model_dump(), sort_keys=True).encode()
    ).hexdigest()
    async with services.db.sessions() as db:
        existing = await db.scalar(
            select(BatchReportJob).where(
                BatchReportJob.idempotency_key == idempotency_key
            )
        )
        if existing:
            if existing.request_hash != digest:
                raise HTTPException(
                    409, "Idempotency-Key reused with a different request."
                )
            return _job_view(existing)
        job = BatchReportJob(
            id=str(uuid.uuid4()),
            idempotency_key=idempotency_key,
            request_hash=digest,
            owner_id=body.owner_id,
            execution_id=body.execution_id,
            batch_run_id=body.batch_run_id,
            request=body.model_dump(),
        )
        db.add(job)
        await db.commit()
        return _job_view(job)


@router.get("/internal/v1/execution-reports/{job_id}")
async def get_report_job(
    job_id: str,
    services: ServicesDep,
    authorization: str | None = Header(None),
):
    _verify_service_token(services, authorization)
    async with services.db.sessions() as db:
        job = await db.get(BatchReportJob, job_id)
    if job is None:
        raise HTTPException(404, "Report job not found.")
    return _job_view(job)


@router.post("/internal/v1/execution-reports/{job_id}/retry", status_code=202)
async def retry_report_job(
    job_id: str,
    services: ServicesDep,
    authorization: str | None = Header(None),
):
    _verify_service_token(services, authorization)
    async with services.db.sessions() as db:
        job = await db.get(BatchReportJob, job_id, with_for_update=True)
        if job is None:
            raise HTTPException(404, "Report job not found.")
        if job.state != "FAILED":
            raise HTTPException(409, "Only failed jobs can be retried.")
        job.state, job.lease_owner, job.lease_expires_at = (
            job.failed_stage or "QUEUED",
            None,
            None,
        )
        await db.commit()
        return _job_view(job)
