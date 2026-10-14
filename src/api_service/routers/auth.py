from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response

from api_service import deps
from api_service.auth.service import SessionRead
from api_service.deps import ServicesDep, UserDep
from api_service.schemas import Model, UserRead
from core.db import get_row
from core.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login/sso", status_code=302)
async def login(
    request: Request, return_to: str = "/", target: str = "app"
) -> Response:
    """Start login with a browser navigation (not XHR)."""
    return await request.app.state.sso.login(request, return_to, target)


@router.get("/login/sso/callback/{flow_id}", status_code=302)
async def callback(request: Request, flow_id: str) -> Response:
    return await request.app.state.sso.callback(request, flow_id)


@router.get("/session", response_model=SessionRead)
async def session(request: Request, response: Response) -> SessionRead:
    """Current login and the CSRF token to send as X-CSRF-Token on writes."""
    return await request.app.state.sso.session(request, response)


@router.post("/logout", status_code=204)
async def logout(request: Request) -> Response:
    return await request.app.state.sso.logout(request)


class DevRole(Model):
    role: Literal["user", "admin"]


@router.post("/dev/role", response_model=UserRead)
async def switch_dev_role(body: DevRole, services: ServicesDep, user: UserDep):
    """Local development only: switch the dev login between user and admin.

    Exists only with ENV=local and SSO_ADAPTER=dev (404 otherwise).
    """
    settings = services.settings
    if settings.env != "local" or settings.sso_adapter != "dev":
        raise HTTPException(404, "Not found.")
    async with services.db.sessions() as db:
        row = await get_row(db, User, user.id)
        row.role = body.role
        await db.commit()
    deps.forget_user(user.id)
    return row
