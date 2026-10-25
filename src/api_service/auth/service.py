import logging
import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from api_service.auth.adapters import SsoAdapter
from api_service.auth.sdk import Employee
from api_service.auth.store import AuthStore, LoginFlow, LoginSession
from api_service.users import bind_employee
from core.config import Settings
from core.db import Database

log = logging.getLogger(__name__)
NO_STORE = {"Cache-Control": "no-store"}


class LoginSessionRead(BaseModel):
    user_id: str
    csrf_token: str
    expires_at: int


class SsoService:
    """Service login on top of corporate SSO.

    Login flow, Redis session cookie, CSRF.
    """

    def __init__(
        self,
        settings: Settings,
        adapter: SsoAdapter,
        store: AuthStore,
        db: Database,
    ):
        self.settings, self.adapter, self.store, self.db = (
            settings,
            adapter,
            store,
            db,
        )

    def _destination(self, return_to: str, target: str) -> str:
        s = self.settings
        if target == "docs":
            return s.public_api_origin + "/docs"
        parsed = urlsplit(return_to)
        if (
            not return_to.startswith("/")
            or return_to.startswith("//")
            or parsed.scheme
            or parsed.netloc
            or any(part in {".", ".."} for part in parsed.path.split("/"))
            or not any(
                parsed.path == root
                or (root != "/" and parsed.path.startswith(root + "/"))
                for root in s.sso_allowed_return_roots
            )
        ):
            raise HTTPException(400, "Invalid return_to.")
        return s.frontend_origin + return_to

    def _checked_login_url(self, url: str, callback: str) -> str:
        if url == callback:
            return url
        parsed = urlsplit(url)
        if (
            f"{parsed.scheme}://{parsed.netloc}"
            in self.settings.sso_allowed_origins
        ):
            return url
        log.warning("sso_login_url_rejected")
        raise HTTPException(
            502, "Corporate SSO returned an invalid login URL."
        )

    async def _verify(self, request: Request) -> Employee | None:
        try:
            return await self.adapter.verify(request)
        except Exception as exc:  # noqa: BLE001 - never leak SDK internals
            log.warning("sso_verify_failed error_type=%s", type(exc).__name__)
            raise HTTPException(503, "Corporate SSO is unavailable.") from None

    async def login(
        self, request: Request, return_to: str = "/", target: str = "app"
    ) -> Response:
        return await self._login(
            request, return_to, target, from_callback=False
        )

    async def callback(self, request: Request, flow_id: str) -> Response:
        flow = await self.store.consume_flow(flow_id)
        if flow is None:
            raise HTTPException(
                400, "Login flow expired or already used. Start login again."
            )
        return await self._login(
            request, flow.return_to, flow.target, from_callback=True
        )

    async def _login(
        self,
        request: Request,
        return_to: str,
        target: str,
        from_callback: bool,
    ) -> Response:
        destination = self._destination(return_to, target)
        employee = await self._verify(request)
        if employee is None:
            if from_callback:
                raise HTTPException(
                    401,
                    "Corporate SSO could not verify the employee.",
                    headers=NO_STORE,
                )
            flow_id = secrets.token_urlsafe(32)
            origin = self.settings.public_api_origin
            prefix = self.settings.api_prefix
            callback = f"{origin}{prefix}/auth/login/sso/callback/{flow_id}"
            url = self._checked_login_url(
                await self.adapter.login_url(request, callback), callback
            )
            await self.store.create_flow(
                flow_id,
                LoginFlow(return_to, target),
                self.settings.login_flow_ttl_seconds,
            )
            return RedirectResponse(url, 302, headers=NO_STORE)
        async with self.db.sessions() as db:
            user = await bind_employee(
                db, employee, self.settings.admin_employee_ids
            )
        if not user.is_active:
            raise HTTPException(403, "This account is disabled.")
        ttl = self.settings.session_ttl_seconds
        sid, _ = await self.store.create_session(user.id, ttl)
        await self.store.revoke_session(
            request.cookies.get(self.settings.session_cookie_name, "")
        )
        response = RedirectResponse(destination, 302, headers=NO_STORE)
        response.set_cookie(
            self.settings.session_cookie_name,
            sid,
            # the server's idle expiry decides; the cookie lasts to the cap
            max_age=self.settings.session_max_seconds,
            path="/",
            secure=self.settings.cookie_secure,
            httponly=True,
            samesite=self.settings.cookie_samesite,
        )
        return response

    async def authenticate(self, request: Request) -> LoginSession:
        sid = request.cookies.get(self.settings.session_cookie_name, "")
        session = await self.store.read_session(sid)
        if session is None:
            raise HTTPException(401, "Login required.")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            token = request.headers.get("x-csrf-token", "")
            if not secrets.compare_digest(
                token.encode(), session.csrf_token.encode()
            ):
                raise HTTPException(
                    403, "A valid X-CSRF-Token header is required."
                )
        return await self.store.touch(
            sid,
            session,
            self.settings.session_ttl_seconds,
            self.settings.session_max_seconds,
        )

    async def session(
        self, request: Request, response: Response
    ) -> LoginSessionRead:
        session = await self.authenticate(request)
        response.headers.update(NO_STORE)
        return LoginSessionRead(
            user_id=session.user_id,
            csrf_token=session.csrf_token,
            expires_at=session.expires_at,
        )

    async def logout(self, request: Request) -> Response:
        await self.authenticate(request)
        await self.store.revoke_session(
            request.cookies.get(self.settings.session_cookie_name, "")
        )
        response = Response(status_code=204, headers=NO_STORE)
        response.delete_cookie(self.settings.session_cookie_name, path="/")
        return response
