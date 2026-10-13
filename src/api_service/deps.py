import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from core.models import ChatSession, Project, ProjectMember, User
from core.services import Services


def get_services(request: Request) -> Services:
    return request.app.state.services


_USER_CACHE: dict[str, tuple[float, User]] = {}
USER_CACHE_SECONDS = 30  # role/deactivation changes apply within this window


async def current_user(request: Request) -> User:
    login = await request.app.state.sso.authenticate(request)
    cached = _USER_CACHE.get(login.user_id)
    if cached and cached[0] > time.monotonic():
        user = cached[1]
    else:
        async with get_services(request).db.sessions() as db:
            user = await db.get(User, login.user_id)
        if len(_USER_CACHE) > 10000:
            _USER_CACHE.clear()
        if user is not None:
            _USER_CACHE[login.user_id] = (
                time.monotonic() + USER_CACHE_SECONDS,
                user,
            )
    if user is None or not user.is_active:
        raise HTTPException(401, "Login required.")
    return user


async def admin_user(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Administrator only.")
    return user


ServicesDep = Annotated[Services, Depends(get_services)]
UserDep = Annotated[User, Depends(current_user)]
AdminDep = Annotated[User, Depends(admin_user)]

WRITE_ROLES = {"owner", "editor"}


async def project_for(
    services: Services, user: User, project_id: str, write: bool = False
) -> Project:
    """Membership decides access.

    Owner today; editor/viewer when projects are shared.
    """
    async with services.db.sessions() as db:
        row = (
            await db.execute(
                select(Project, ProjectMember.role)
                .join(ProjectMember, ProjectMember.project_id == Project.id)
                .where(
                    Project.id == project_id,
                    ProjectMember.user_id == user.id,
                    Project.deleted_at.is_(None),
                )
            )
        ).first()
    if row is None:
        raise HTTPException(404, "Project not found.")
    project, role = row
    if write and role not in WRITE_ROLES:
        raise HTTPException(403, "Read-only access to this project.")
    return project


async def session_for(
    services: Services, user: User, session_id: str, write: bool = False
) -> ChatSession:
    async with services.db.sessions() as db:
        session = await db.get(ChatSession, session_id)
    if session is None or session.deleted_at is not None:
        raise HTTPException(404, "Session not found.")
    await project_for(services, user, session.project_id, write)
    return session
