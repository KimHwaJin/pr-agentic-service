from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from api_service.deps import ServicesDep, UserDep, project_for
from api_service.schemas.projects import (
    MemoryCreate,
    MemoryUpdate,
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
)
from core.db import get_row, utcnow
from core.memory.service import Actor, MemoryItemError
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


def _memory_error(exc: MemoryItemError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


@router.get("/{project_id}/memory")
async def list_memory(project_id: str, services: ServicesDep, user: UserDep):
    await project_for(services, user, project_id)
    items = await services.memory.entries(project_id)
    return {
        "items": items,
        "total_chars": sum(len(i["content"]) for i in items),
        "max_chars": services.settings.memory_total_max_chars,
    }


@router.post("/{project_id}/memory", status_code=201)
async def create_memory(
    project_id: str, body: MemoryCreate, services: ServicesDep, user: UserDep
):
    await project_for(services, user, project_id, write=True)
    try:
        return await services.memory.create(
            project_id, **body.model_dump(), actor=Actor("user", user.id)
        )
    except MemoryItemError as exc:
        raise _memory_error(exc) from None


@router.patch("/{project_id}/memory/{item_id}")
async def update_memory(
    project_id: str,
    item_id: str,
    body: MemoryUpdate,
    services: ServicesDep,
    user: UserDep,
):
    await project_for(services, user, project_id, write=True)
    try:
        return await services.memory.update(
            project_id,
            item_id,
            actor=Actor("user", user.id),
            **body.model_dump(),
        )
    except MemoryItemError as exc:
        raise _memory_error(exc) from None


@router.delete("/{project_id}/memory/{item_id}", status_code=204)
async def delete_memory(
    project_id: str,
    item_id: str,
    expected_version: int,
    services: ServicesDep,
    user: UserDep,
):
    await project_for(services, user, project_id, write=True)
    try:
        await services.memory.delete(
            project_id,
            item_id,
            expected_version=expected_version,
            actor=Actor("user", user.id),
        )
    except MemoryItemError as exc:
        raise _memory_error(exc) from None
    return Response(status_code=204)


@router.get("/{project_id}/memory/history")
async def memory_history(
    project_id: str,
    services: ServicesDep,
    user: UserDep,
    item_id: str | None = None,
):
    await project_for(services, user, project_id)
    return {"items": await services.memory.history(project_id, item_id)}
