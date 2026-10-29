from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import select

from api_service.deps import ServicesDep, UserDep, project_for
from api_service.schemas.projects import (
    MemoryContentWrite,
    MemoryHistoryRead,
    MemoryRead,
    MemoryRevert,
    MemoryTopicContent,
    MemoryTopicsRead,
    MemoryTopicsWrite,
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
)
from core.db import get_row, utcnow
from core.memory.service import Actor, MemoryEditError
from core.models import Project, ProjectMember

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectRead])
async def list_projects(services: ServicesDep, user: UserDep):
    async with services.db.sessions() as db:
        rows = await db.scalars(
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(
                ProjectMember.user_id == user.id, Project.deleted_at.is_(None)
            )
            .order_by(Project.is_default.desc(), Project.updated_at.desc())
        )
        return rows.all()


@router.post("", response_model=ProjectRead, status_code=201)
async def create_project(
    body: ProjectCreate, services: ServicesDep, user: UserDep
):
    async with services.db.sessions() as db:
        project = Project(**body.model_dump(), created_by=user.id)
        db.add(project)
        await db.flush()
        db.add(
            ProjectMember(project_id=project.id, user_id=user.id, role="owner")
        )
        await db.commit()
        return project


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(project_id: str, services: ServicesDep, user: UserDep):
    return await project_for(services, user, project_id)


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: str, body: ProjectUpdate, services: ServicesDep, user: UserDep
):
    await project_for(services, user, project_id, write=True)
    async with services.db.sessions() as db:
        project = await db.get(Project, project_id)
        for key, value in body.changes(nullable={"code_level"}).items():
            setattr(project, key, value)
        await db.commit()
        return project


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str, services: ServicesDep, user: UserDep
):
    project = await project_for(services, user, project_id, write=True)
    if project.is_default:
        raise HTTPException(409, "The default project cannot be deleted.")
    async with services.db.sessions() as db:
        (await get_row(db, Project, project_id)).deleted_at = utcnow()
        await db.commit()
    return Response(status_code=204)


# --- project shared memory -------------------------------------------------


def _memory_error(exc: MemoryEditError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


@router.get("/{project_id}/memory", response_model=MemoryRead)
async def get_memory(project_id: str, services: ServicesDep, user: UserDep):
    """Every topic in order with its body, empty ones included."""
    await project_for(services, user, project_id)
    return await services.memory.memory(project_id)


@router.get("/{project_id}/memory/topics", response_model=MemoryTopicsRead)
async def get_memory_topics(
    project_id: str, services: ServicesDep, user: UserDep
):
    await project_for(services, user, project_id)
    return await services.memory.topic_list(project_id)


@router.put("/{project_id}/memory/topics", response_model=MemoryTopicsRead)
async def put_memory_topics(
    project_id: str,
    body: MemoryTopicsWrite,
    services: ServicesDep,
    user: UserDep,
):
    """Replace the topic list. Same id = edit (body kept); no id or
    ``replace`` = a new, empty topic; a dropped topic's body is cleared
    and can be restored from history."""
    await project_for(services, user, project_id, write=True)
    try:
        return await services.memory.put_topics(
            project_id,
            [t.model_dump() for t in body.topics],
            expected_version=body.expected_version,
            actor=Actor("user", user.id),
        )
    except MemoryEditError as exc:
        raise _memory_error(exc) from None


@router.get("/{project_id}/memory/history", response_model=MemoryHistoryRead)
async def memory_history(
    project_id: str,
    services: ServicesDep,
    user: UserDep,
    topic: str | None = None,
    removed: bool = Query(
        False, description="only replaced/removed topics (restorable)"
    ),
    limit: int = Query(100, ge=1, le=500),
):
    await project_for(services, user, project_id)
    return {
        "items": await services.memory.history(
            project_id, topic, limit, removed=removed
        )
    }


@router.post(
    "/{project_id}/memory/history/{history_id}/restore",
    response_model=MemoryRead,
)
async def restore_memory_topic(
    project_id: str, history_id: int, services: ServicesDep, user: UserDep
):
    """Bring back a replaced or removed topic with its body (added at the
    end of the list)."""
    await project_for(services, user, project_id, write=True)
    try:
        return await services.memory.restore(
            project_id, history_id, actor=Actor("user", user.id)
        )
    except MemoryEditError as exc:
        raise _memory_error(exc) from None


@router.put(
    "/{project_id}/memory/{topic_id}", response_model=MemoryTopicContent
)
async def put_memory_content(
    project_id: str,
    topic_id: str,
    body: MemoryContentWrite,
    services: ServicesDep,
    user: UserDep,
):
    """Replace a topic's body; unchanged lines keep their author."""
    await project_for(services, user, project_id, write=True)
    try:
        return await services.memory.put_content(
            project_id,
            topic_id,
            body.content,
            expected_version=body.expected_version,
            actor=Actor("user", user.id),
        )
    except MemoryEditError as exc:
        raise _memory_error(exc) from None


@router.post(
    "/{project_id}/memory/{topic_id}/revert",
    response_model=MemoryTopicContent,
)
async def revert_memory_content(
    project_id: str,
    topic_id: str,
    body: MemoryRevert,
    services: ServicesDep,
    user: UserDep,
):
    """Undo one history entry of the topic (a new version)."""
    await project_for(services, user, project_id, write=True)
    try:
        return await services.memory.revert(
            project_id,
            topic_id,
            body.history_id,
            actor=Actor("user", user.id),
            expected_version=body.expected_version,
        )
    except MemoryEditError as exc:
        raise _memory_error(exc) from None
