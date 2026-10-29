import re
import time
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import func, select

from api_service.errors import ApiError
from api_service.services import api_clients
from api_service.services.api_clients import Caller
from core.models import ChatSession, Project, ProjectMember, User
from core.services import Services

USER_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")


def get_services(request: Request) -> Services:
    return request.app.state.services


_USER_CACHE: dict[str, tuple[float, User]] = {}
USER_CACHE_SECONDS = 30  # role/deactivation changes apply within this window


# Shown in OpenAPI (Swagger "Authorize"); current_user reads the headers.
API_KEY = APIKeyHeader(
    name="X-Api-Key",
    scheme_name="X-Api-Key",
    auto_error=False,
    description="Key of a service or agent (시스템 > API 키). Not with the "
    "SSO cookie: a request with the cookie is decided by it alone.",
)
USER_HEADER = APIKeyHeader(
    name="X-User-Id",
    scheme_name="X-User-Id",
    auto_error=False,
    description="Our users.id the key caller acts for (required with "
    "X-Api-Key; alone in AUTH_MODE=header, local/dev).",
)


async def identity_headers(
    x_api_key: Annotated[str | None, Security(API_KEY)] = None,
    x_user_id: Annotated[str | None, Security(USER_HEADER)] = None,
    x_project_id: Annotated[
        str | None,
        Header(
            alias="X-Project-Id",
            description="Key callers, optional: must repeat the path's "
            "project; on the executor and batch gateways the project the "
            "call is for.",
        ),
    ] = None,
    x_session_id: Annotated[
        str | None,
        Header(
            alias="X-Session-Id",
            description="Key callers, optional (needs X-Project-Id).",
        ),
    ] = None,
) -> None:
    """Documents the caller headers; ``current_user`` checks them."""


IdentityHeaders = Annotated[None, Depends(identity_headers)]


async def current_user(
    request: Request, _headers: IdentityHeaders = None
) -> User:
    """The SSO user of the cookie, else the user a key caller names.

    A request with the session cookie is decided by SSO alone (CSRF
    included). Without it, ``X-Api-Key`` names an active api client and
    ``X-User-Id`` one of our active users (``users.id`` or employee id);
    ``AUTH_MODE=header`` (local/dev)
    trusts ``X-User-Id`` without a key. The caller is kept on
    ``request.state.api_client`` (None for SSO).
    """
    services = get_services(request)
    settings = services.settings
    request.state.api_client = None
    if request.cookies.get(settings.session_cookie_name):
        login = await request.app.state.sso.authenticate(request)
        user = await _user(services, login.user_id)
        if user is None or not user.is_active:
            raise HTTPException(401, "Login required.")
        return user
    _, _, user = await key_identity(request, services)
    assert user is not None
    return user


async def key_identity(
    request: Request,
    services: Services,
    user_required: bool = True,
    any_user_outside: bool = False,
) -> tuple[Caller, str | None, User | None]:
    """(api client, user id to send on, our user) of a keyed request.

    ``X-User-Id`` names one of our active users (``users.id`` or employee
    id, sent on as ``users.id``). ``any_user_outside`` (the executor and
    batch gateways): a client of another tenant works in that tenant's own
    space, so its user ids are its own and only checked for form (no user
    of ours). ``user_required`` False (gateway reads): without
    ``X-User-Id`` the request is a system read over the client's tenant.
    """
    caller = await _caller(request, services)
    request.state.api_client = caller
    user_id = identity_header(request, "x-user-id", USER_ID, lower=True)
    _same_as_path(request)
    if user_id is None:
        if user_required:
            raise invalid_identity("X-User-Id is required.")
        return caller, None, None
    if (
        any_user_outside
        and caller.tenant != services.settings.executor_tenant_id
    ):
        request.state.caller_user_id = user_id
        return caller, user_id, None
    user = await _user(services, user_id)
    if user is None or not user.is_active:
        raise HTTPException(403, "Unknown or inactive user.")
    request.state.caller_user_id = user.id
    return caller, user.id, user


async def _caller(request: Request, services: Services) -> Caller:
    settings = services.settings
    key = request.headers.get("x-api-key", "")
    if key:
        caller = await api_clients.verify(services, key)
        if caller is None:
            raise ApiError(401, "invalid_api_key", "Unknown API key.")
        return caller
    if settings.auth_mode == "header":
        return Caller("header", "header", settings.executor_tenant_id)
    raise HTTPException(401, "Login required.")


def identity_header(
    request: Request, name: str, pattern: re.Pattern, lower: bool = False
) -> str | None:
    """A caller's identity header, checked (400 when malformed)."""
    value = request.headers.get(name, "").strip()
    if not value:
        return None
    if lower:
        value = value.lower()
    if not pattern.fullmatch(value) or value == "unscoped":
        raise invalid_identity(f"{name} is malformed.")
    return value


def invalid_identity(detail: str) -> ApiError:
    return ApiError(400, "INVALID_IDENTITY", detail)


def _same_as_path(request: Request) -> None:
    """X-Project-Id / X-Session-Id may only repeat the path's ids."""
    project = identity_header(request, "x-project-id", PROJECT_ID)
    session = request.headers.get("x-session-id", "").strip()
    if session and not project:
        raise invalid_identity("X-Session-Id needs X-Project-Id.")
    path = request.path_params
    if project and "project_id" in path and path["project_id"] != project:
        raise invalid_identity("X-Project-Id differs from the path.")
    if session and "session_id" in path and path["session_id"] != session:
        raise invalid_identity("X-Session-Id differs from the path.")


async def _user(services: Services, user_id: str) -> User | None:
    """Our user by ``users.id``, else by employee id (key callers)."""
    cached = _USER_CACHE.get(user_id)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    async with services.db.sessions() as db:
        user = await db.get(User, user_id) if UUID.fullmatch(user_id) else None
        if user is None:
            user = await db.scalar(
                select(User).where(func.lower(User.employee_id) == user_id)
            )
    if len(_USER_CACHE) > 10000:
        _USER_CACHE.clear()
    if user is not None:
        _USER_CACHE[user_id] = (time.monotonic() + USER_CACHE_SECONDS, user)
    return user


def caller_of(request: Request) -> Caller | None:
    """The api client of a key request (after ``current_user``)."""
    return getattr(request.state, "api_client", None)


def forget_user(user_id: str) -> None:
    """Drop the cached user so a role change applies to the next request."""
    _USER_CACHE.pop(user_id, None)


async def admin_user(
    request: Request, user: Annotated[User, Depends(current_user)]
) -> User:
    if caller_of(request) is not None:
        raise HTTPException(403, "Administrator APIs need an SSO login.")
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
