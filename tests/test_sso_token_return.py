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

    async def consume_flow(self, flow_id):
        return self.flows.pop(flow_id, None)


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
    monkeypatch.setattr(idp_login, "LOGIN_TARGET", "callback")

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


def test_userinfo_without_amtoken_goes_to_the_token_page(monkeypatch):
    from src.dtest import idp_login

    class Cookies(dict):
        def to_dict(self):
            return dict(self)

    class View:
        def __init__(self, cookies):
            self.cookies = Cookies(cookies)
            self.environ = {"HTTP_HOST": "agentic.corp"}

    monkeypatch.setattr(idp_login, "VERIFY_WITH", "userinfo")
    monkeypatch.setattr(idp_login, "LOGIN_TARGET", "callback")
    monkeypatch.setattr(idp_login, "TOKEN_PAGE", "http://login.corp/issue.jsp")
    fresh = idp_login.create_sdk(View({"SMSESSION": "s"}), "https://cb")
    assert fresh.redirect_url == (
        "http://login.corp/issue.jsp"
        "?client_id=agentic.corp&redirect_uri=agentic.corp"
    )
    # with an AMTOKEN (expired or refused): the SSO login, as before
    known = idp_login.create_sdk(
        View({"SMSESSION": "s", "AMTOKEN": "a"}), "https://cb"
    )
    assert known.redirect_url.endswith("?TARGET=https://cb")
    # not logged in to the SSO yet: its login first (the token page
    # calls a missing SMSESSION an expired session)
    assert idp_login.create_sdk(View({}), "https://cb").redirect_url.endswith(
        "?TARGET=https://cb"
    )
    # no token page configured: as before
    monkeypatch.setattr(idp_login, "TOKEN_PAGE", "")
    assert idp_login.create_sdk(View({}), "https://cb").redirect_url.endswith(
        "?TARGET=https://cb"
    )


def test_a_callback_without_amtoken_goes_on_to_the_token_page_once():
    from src.dtest.api_service.auth.store import AuthFlow

    sso = _service(TOKEN_PAGE)
    sso.store.flows["f" * 43] = AuthFlow("/dev/", "app")  # back from login
    on = asyncio.run(sso.callback(_request(), "f" * 43))
    assert on.headers["location"] == TOKEN_PAGE
    (flow,) = sso.store.flows.values()
    assert flow.hops == 1 and flow.return_to == "/dev/"
    # back from the token page still unverified: stop, no loop
    (flow_id,) = sso.store.flows
    with pytest.raises(HTTPException) as e:
        asyncio.run(sso.callback(_request(), flow_id))
    assert e.value.status_code == 401


def test_userinfo_takes_the_token_page_url_the_workplace_gives(monkeypatch):
    import httpx

    from src.dtest import idp_login

    calls = []

    class Response:
        status_code = 401

        def json(self):
            return {"url": "http://login.corp/issuToken.jsp?cliend_id=a"}

    def fake_get(url, params, headers, cookies, timeout):
        calls.append((url, params, headers, cookies))
        return Response()

    class Cookies(dict):
        def to_dict(self):
            return dict(self)

    class View:
        cookies = Cookies({"SMSESSION": "s"})
        environ = {"HTTP_HOST": "agentic.corp"}

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(idp_login, "VERIFY_WITH", "userinfo")
    monkeypatch.setattr(idp_login, "SSO_CHECK_URL", "http://wp.corp/sso")
    monkeypatch.setattr(idp_login, "TOKEN_PAGE", "http://never")
    sso = idp_login.create_sdk(View(), "https://cb")
    assert sso.redirect_url == "http://login.corp/issuToken.jsp?cliend_id=a"
    assert calls == [
        (
            "http://wp.corp/sso",
            {"URL": "agentic.corp"},
            {"Client-Url": "agentic.corp"},
            {"SMSESSION": "s"},
        )
    ]

    # the workplace says something else: TOKEN_PAGE, as configured
    Response.status_code = 200
    sso = idp_login.create_sdk(View(), "https://cb")
    assert sso.redirect_url.startswith("http://never?client_id=")
