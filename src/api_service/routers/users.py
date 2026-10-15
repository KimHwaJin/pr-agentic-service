from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from api_service.deps import AdminDep, ServicesDep, UserDep
from api_service.schemas.users import Me, UserAdminUpdate, UserRead
from core.models import Project, ProjectMember, User

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
        for key, value in body.model_dump(exclude_unset=True).items():
            setattr(user, key, value)
        await db.commit()
        return user
