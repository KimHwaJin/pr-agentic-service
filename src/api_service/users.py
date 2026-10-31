from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from api_service.auth.sdk import Employee
from core.db import new_id
from core.models import Project, ProjectMember, User


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
            id=new_id(),
            employee_id=employee.employee_id,
            name=employee.name,
            role="admin" if employee.employee_id in admin_ids else "user",
        )
        .on_conflict_do_nothing(index_elements=[User.employee_id])
        .returning(User.id)
    )
    user = await db.scalar(
        select(User).where(User.employee_id == employee.employee_id)
    )
    assert user is not None
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
