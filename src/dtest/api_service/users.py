from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.dtest.api_service.auth.sdk import Employee
from src.dtest.core.models import Project, ProjectMember, User


async def bind_employee(
    db: AsyncSession, employee: Employee, admin_ids: list[str]
) -> User:
    """First login creates the user with a default project.

    Later logins refresh the profile.
    """
    user = await db.scalar(
        select(User).where(User.employee_id == employee.employee_id)
    )
    if user is None:
        user = User(employee_id=employee.employee_id, name=employee.name)
        user.role = "admin" if employee.employee_id in admin_ids else "user"
        db.add(user)
        await db.flush()
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
