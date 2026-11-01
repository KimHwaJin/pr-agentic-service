import re

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from api_service.auth.sdk import Employee
from core.models import Project, ProjectMember, User

# X-User-Id of the executor and pr-batch, and our users.id column (36)
EMPLOYEE_USER_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,35}$")


def user_id_of(employee_id: str) -> str:
    """Our ``users.id`` of an employee: the SSO employee id, lowercased.

    The executor and pr-batch know a person by employee id in every
    tenant (2026-11-01), and ``users.id`` is what we send as
    ``X-User-Id``, so the two are one value. Users created before then
    keep their uuid until the databases are reset.
    """
    user_id = employee_id.strip().lower()
    if not EMPLOYEE_USER_ID.fullmatch(user_id):
        raise HTTPException(
            403, "This employee id cannot be used as a user id."
        )
    return user_id


async def bind_employee(
    db: AsyncSession, employee: Employee, admin_ids: list[str]
) -> User:
    """First login creates the user with a default project.

    Later logins refresh the profile.
    """
    # two first logins at once (two tabs): one insert wins, the other
    # finds the row instead of failing on the unique employee_id
    created = await db.scalar(
        insert(User)
        .values(
            id=user_id_of(employee.employee_id),
            employee_id=employee.employee_id,
            name=employee.name,
            role="admin" if employee.employee_id in admin_ids else "user",
        )
        # any conflict: the same employee (above), or a users.id taken by
        # an employee id differing only in case (refused below)
        .on_conflict_do_nothing()
        .returning(User.id)
    )
    user = await db.scalar(
        select(User).where(User.employee_id == employee.employee_id)
    )
    if user is None:
        raise HTTPException(
            403, "This employee id cannot be used as a user id."
        )
    if created:
        project = Project(
            name="기본 프로젝트", is_default=True, created_by=user.id
        )
        db.add(project)
        await db.flush()
        db.add(
            ProjectMember(project_id=project.id, user_id=user.id, role="owner")
        )
    user.name = employee.name
    user.english_name, user.department, user.email = (
        employee.english_name,
        employee.department,
        employee.email,
    )
    await db.commit()
    return user
