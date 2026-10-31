from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from src.dtest.api_service.deps import (
    AdminDep,
    ServicesDep,
    UserDep,
    forget_user,
)
from src.dtest.api_service.schemas.users import (
    Me,
    UserAdminUpdate,
    UserBrief,
    UserRead,
)
from src.dtest.api_service.services.runs import request_cancel
from src.dtest.core.batch_admin import tell_batch
from src.dtest.core.executor.cancels import cancel_idle_executions
from src.dtest.core.models import (
    ChatSession,
    Project,
    ProjectMember,
    Run,
    User,
)
from src.dtest.core.services import Services

router = APIRouter(tags=["users"])


@router.get("/users/me", response_model=Me)
async def me(services: ServicesDep, user: UserDep):
    async with services.db.sessions() as db:
        default_project = await db.scalar(
            select(Project.id)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(
                ProjectMember.user_id == user.id,
                Project.is_default,
                Project.deleted_at.is_(None),
            )
        )
    settings = services.settings
    return Me(
        user=UserRead.model_validate(user),
        default_project_id=default_project,
        can_switch_role=settings.env == "local"
        and settings.sso_adapter == "dev",
    )


@router.get("/users/lookup", response_model=dict[str, UserBrief])
async def lookup_users(services: ServicesDep, user: UserDep, ids: str = ""):
    """Names of user ids shown on a page (executor ``context.user_id``).

    ``ids`` is comma separated, at most 200. A user resolves only their own
    id; an administrator resolves anyone's. Unknown ids are left out.
    """
    wanted = list(
        dict.fromkeys(i.strip() for i in ids.split(",") if i.strip())
    )
    if len(wanted) > 200:
        raise HTTPException(422, "At most 200 ids.")
    return await users_by_id(
        services,
        wanted
        if user.role == "admin"
        else [i for i in wanted if i == user.id],
    )


async def users_by_id(services, ids: list[str]) -> dict[str, User]:
    if not ids:
        return {}
    async with services.db.sessions() as db:
        rows = (await db.scalars(select(User).where(User.id.in_(ids)))).all()
    return {u.id: u for u in rows}


@router.get("/admin/users", response_model=list[UserRead])
async def list_users(
    services: ServicesDep, admin: AdminDep, q: str | None = None
):
    query = select(User).order_by(User.created_at.desc()).limit(500)
    if q:
        query = query.where(
            User.name.ilike(f"%{q}%") | User.employee_id.ilike(f"%{q}%")
        )
    async with services.db.sessions() as db:
        return (await db.scalars(query)).all()


@router.patch("/admin/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: str, body: UserAdminUpdate, services: ServicesDep, admin: AdminDep
):
    if user_id == admin.id and body.is_active is False:
        raise HTTPException(409, "You cannot deactivate yourself.")
    async with services.db.sessions() as db:
        user = await db.get(User, user_id)
        if user is None:
            raise HTTPException(404, "User not found.")
        changes = body.changes()
        deactivated = changes.get("is_active") is False
        for key, value in changes.items():
            setattr(user, key, value)
        if "is_active" in changes:
            # pr-batch turns their batches off (idempotent, retried by the
            # worker); reactivating does not turn them back on
            user.batches_disable_pending = deactivated
        await db.commit()
    forget_user(user_id)
    if deactivated:
        await tell_batch(services, user_id)
        await stop_user_work(services, user_id)
    async with services.db.sessions() as db:
        return await db.get(User, user_id)


async def stop_user_work(services: Services, user_id: str) -> None:
    """A deactivated user's turns and executor kernels stop with them.

    Their running or waiting runs are cancelled (the executor execution a
    run waits on included); kernels their sessions may still keep open
    are cancelled as on a session delete. Cancels the executor misses are
    retried by the worker.
    """
    async with services.db.sessions() as db:
        runs = (
            await db.scalars(
                select(Run.id).where(
                    Run.user_id == user_id,
                    Run.status.notin_(("succeeded", "failed", "cancelled")),
                )
            )
        ).all()
        sessions = (
            await db.scalars(
                select(ChatSession.id).where(ChatSession.user_id == user_id)
            )
        ).all()
    for run_id in runs:
        await request_cancel(services, run_id, "사용자 비활성화")
    await cancel_idle_executions(
        services, list(sessions), reason="사용자 비활성화"
    )
