"""The SDK's token page returns to our root, not the callback: the login
flow rides a short cookie from the redirect to ``GET /``."""

import asyncio

import pytest
from fastapi import HTTPException, Request

from src.dtest.api_service.auth.service import LOGIN_FLOW_COOKIE, SsoService
from src.dtest.api_service.paths import is_own
from src.dtest.core.config import Settings

TOKEN_PAGE = "http://login.corp/sso/agentless/issueToken.jsp?client_id=a"


class Adapter:
    def __init__(self, url):
        self.url = url

    async def verify(self, request):
        return None

    async def entry_url(self, request, callback):
        return self.url or callback


class Store:
    def __init__(self):
        self.flows = {}

    async def create_flow(self, flow_id, flow, ttl):
        self.flows[flow_id] = flow


def _service(url, **kw):
    s = Settings(
        public_api_origin="https://agentic.corp",
        sso_allowed_origins=["http://login.corp"],
        web_console_enabled=True,
        **kw,
    )
    return SsoService(s, Adapter(url), Store(), None)


def _request(cookie: str = "", query: bytes = b"") -> Request:
    headers = [(b"cookie", cookie.encode())] if cookie else []
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": query,
            "headers": headers,
        }
    )


def _set_cookies(response) -> list[str]:
    return [
        v.decode()
        for k, v in response.raw_headers
        if k.decode().lower() == "set-cookie"
    ]


def test_a_redirect_to_the_token_page_keeps_the_flow():
    sso = _service(TOKEN_PAGE)
    response = asyncio.run(sso.start(_request(), "/dev/"))
    assert response.headers["location"] == TOKEN_PAGE
    (cookie,) = _set_cookies(response)
    flow_id = cookie.split(";")[0].split("=", 1)[1]
    assert cookie.startswith(LOGIN_FLOW_COOKIE + "=")
    assert "samesite=lax" in cookie.lower() and "httponly" in cookie.lower()
    assert flow_id in sso.store.flows


def test_the_callback_route_sets_no_flow_cookie():
    sso = _service(None)  # entry is our callback (dev adapter style)
    response = asyncio.run(sso.start(_request(), "/dev/"))
    assert "/auth/login/sso/callback/" in response.headers["location"]
    assert _set_cookies(response) == []


def test_root_goes_on_with_the_flow_else_to_the_console():
    sso = _service(TOKEN_PAGE)
    flow_id = "a" * 43
    back = sso.returned(_request(f"{LOGIN_FLOW_COOKIE}={flow_id}"))
    assert back.headers["location"] == (
        f"/api/v1/auth/login/sso/callback/{flow_id}"
    )
    assert sso.returned(_request()).headers["location"] == "/dev/"
    # a malformed cookie is ignored
    bad = sso.returned(_request(f"{LOGIN_FLOW_COOKIE}=../x"))
    assert bad.headers["location"] == "/dev/"


def test_root_without_a_flow_is_not_found_when_the_console_is_off():
    sso = _service(TOKEN_PAGE)
    sso.settings.web_console_enabled = False
    with pytest.raises(HTTPException) as e:
        sso.returned(_request())
    assert e.value.status_code == 404


def test_root_is_one_of_our_paths():
    """the gaia template's access key check must not stop the browser"""
    assert is_own("/")
    assert not is_own("/api/admin/appReady")


def test_idp_login_sdk_mode_keeps_the_sdk_login_url(monkeypatch):
    import sys
    import types

    from src.dtest import idp_login

    class SSO:
        def __init__(self, request):
            self.redirect_url = TOKEN_PAGE

    module = types.ModuleType("your_private_module")
    module.SSO = SSO
    monkeypatch.setitem(sys.modules, "your_private_module", module)
    monkeypatch.setattr(idp_login, "VERIFY_WITH", "sdk")

    class Args(dict):
        def to_dict(self):
            return dict(self)

    class View:
        args = Args()
        environ = {"HTTP_HOST": "agentic.corp"}

    assert (
        idp_login.create_sdk(View(), "https://cb").redirect_url == TOKEN_PAGE
    )
    monkeypatch.setattr(idp_login, "VERIFY_WITH", "userinfo")

    class Cookies(dict):
        def to_dict(self):
            return dict(self)

    class UView:
        cookies = Cookies()

    assert idp_login.create_sdk(UView(), "https://cb").redirect_url.endswith(
        "TARGET=https://cb"
    )


def test_root_hands_the_token_page_query_to_the_callback():
    sso = _service(TOKEN_PAGE)
    flow_id = "b" * 43
    back = sso.returned(
        _request(f"{LOGIN_FLOW_COOKIE}={flow_id}", b"ssoToken=abc%2B1&x=2")
    )
    assert back.headers["location"] == (
        f"/api/v1/auth/login/sso/callback/{flow_id}?ssoToken=abc%2B1&x=2"
    )
