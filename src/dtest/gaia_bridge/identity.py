"""gaia caller -> our user and chat session.

gaia sends the employee id (the same one SSO gives) and its own session
id. A first-time employee gets a user with a default project, as a first
SSO login does; each gaia session gets one of our sessions in that
project, so the conversation also shows in our own UI.
"""

from sqlalchemy import select

from src.dtest.api_service.auth.sdk import Employee
from src.dtest.api_service.users import bind_employee
from src.dtest.core.models import ChatSession, Project, ProjectMember, User
from src.dtest.core.services import Services
from src.dtest.gaia_bridge.models import GaiaSession


async def user_for(services: Services, employee_id: str) -> User:
    async with services.db.sessions() as db:
        user = await db.scalar(
            select(User).where(User.employee_id == employee_id)
        )
        if user is not None:
            return user
        # name unknown until the first SSO login, which refreshes it
        return await bind_employee(
            db,
            Employee(employee_id=employee_id, name=employee_id),
            services.settings.admin_employee_ids,
        )


async def session_for(
    services: Services, user: User, gaia_session_id: str, first_text: str
) -> str:
    """Our session id for this gaia session (created on first use, and
    again when the user deleted it in our UI)."""
    async with services.db.sessions() as db:
        link = await db.get(GaiaSession, (user.id, gaia_session_id))
        if link is not None:
            current = await db.get(ChatSession, link.session_id)
            if current is not None and current.deleted_at is None:
                return current.id
        project_id = await db.scalar(
            select(Project.id)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user.id, Project.is_default)
        )
        if project_id is None:
            raise LookupError(f"user {user.id} has no default project")
        session = ChatSession(
            project_id=project_id, user_id=user.id, title=first_text[:40]
        )
        db.add(session)
        await db.flush()
        if link is None:
            db.add(
                GaiaSession(
                    user_id=user.id,
                    gaia_session_id=gaia_session_id,
                    session_id=session.id,
                )
            )
        else:
            link.session_id = session.id
        await db.commit()
        return session.id
