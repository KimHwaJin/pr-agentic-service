"""Who may see an execution or an artifact.

The executor has no user authentication, so every route that reaches an
execution or artifact through this service checks access here: by project
membership (via the session or our code-source index), else by the
execution's own context. User ids are our ``users.id`` (UUID) everywhere:
executor ``context.user_id``, pr-batch owners and actors.
"""

import time

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from api_service.deps import project_for, session_for
from api_service.errors import ApiError
from core.executor.client import ExecutorError, trigger_type
from core.models import CodeSource, User
from core.services import Services

OWNER_TTL = 300.0  # an execution's project never changes
_owners: dict[str, tuple[float, str | None, str]] = {}


async def scope_execution_list(
    services: Services, user: User, params: dict[str, str]
) -> None:
    """Only the caller's executions, inside projects they belong to."""
    if session_id := params.get("session_id"):
        session = await session_for(services, user, session_id)
        params["project_id"] = session.project_id
    elif project_id := params.get("project_id"):
        await project_for(services, user, project_id)
    params["user_id"] = user.id


async def check_execution(
    services: Services, user: User, execution_id: str
) -> None:
    project_id, owner = await execution_owner(services, execution_id)
    if project_id is not None:
        await project_for(services, user, project_id)  # 404 when not a member
    elif owner != user.id:
        raise HTTPException(404, "Execution not found.")


async def execution_owner(
    services: Services, execution_id: str
) -> tuple[str | None, str]:
    """(project id, user id) of an execution, cached."""
    hit = _owners.get(execution_id)
    if hit and hit[0] > time.monotonic():
        return hit[1], hit[2]
    async with services.db.sessions() as db:
        row = (
            await db.execute(
                select(CodeSource.project_id, CodeSource.user_id)
                .where(CodeSource.execution_id == execution_id)
                .limit(1)
            )
        ).first()
    if row is not None:
        owner = (row.project_id, row.user_id)
    else:  # not sent by this service (e.g. pr-batch): ask the executor
        try:
            execution = await services.executor.get(execution_id)
        except ExecutorError as exc:
            if exc.status == 404:
                raise HTTPException(404, "Execution not found.") from None
            raise executor_unavailable() from None
        except httpx.HTTPError:
            raise executor_unavailable() from None
        context = execution.get("context") or {}
        owner = (context.get("project_id"), context.get("user_id", ""))
    _owners[execution_id] = (time.monotonic() + OWNER_TTL, *owner)
    if len(_owners) > 10000:
        _owners.clear()
    return owner


async def execution_of_session(
    services: Services, execution_id: str, session_id: str
) -> bool:
    """Our index answers without calling the executor per image."""
    async with services.db.sessions() as db:
        owner = await db.scalar(
            select(CodeSource.session_id)
            .where(CodeSource.execution_id == execution_id)
            .limit(1)
        )
    return owner == session_id


async def owned_artifact(services, user, artifact_id: str) -> dict:
    """A session's artifact for its project members.

    A batch execution's artifact (its notebook, its report) for the user
    who owns the batch.
    """
    try:
        artifact = await services.executor.artifact(artifact_id)
        execution = await services.executor.get(
            artifact["produced_by"]["execution_id"]
        )
    except ExecutorError:
        raise HTTPException(404, "Artifact not found.") from None
    context = execution.get("context") or {}
    if trigger_type(execution) == "BATCH":
        if context.get("user_id") != user.id:
            raise HTTPException(404, "Artifact not found.")
        return artifact
    session_id = context.get("session_id")
    if not session_id:
        raise HTTPException(404, "Artifact not found.")
    await session_for(services, user, session_id)
    return artifact


def executor_unavailable() -> ApiError:
    return ApiError(
        502, "executor_unavailable", "The executor did not answer."
    )
