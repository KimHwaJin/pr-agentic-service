from fastapi import APIRouter, Request, Response

from api_service.auth.service import SessionRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login/sso", status_code=302)
async def login(request: Request, return_to: str = "/", target: str = "app") -> Response:
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
