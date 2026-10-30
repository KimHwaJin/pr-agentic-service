from fastapi import Request

from api_service.auth.sdk import login_url, verify_employee


def _request(cookie: str | None = None, query: bytes = b"") -> Request:
    headers = [(b"cookie", cookie.encode())] if cookie else []
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/login",
            "query_string": query,
            "headers": headers,
            "server": ("api", 443),
            "scheme": "https",
        }
    )


class FakeSdk:
    def __init__(self, request, callback):
        self.request, self.callback = request, callback
        self.redirect_url = (
            "https://sso.example/login?ORIGIN="
            + request.args.to_dict()["ORIGIN"]
            if callback
            else ""
        )

    def check_day_cookie(self, cookie):
        return "valid" in cookie

    def get_sso_info(self, cookie):
        return ("00123", "홍길동", "Hong", "데이터팀", "hong@example.com")


def test_verify_employee_keeps_leading_zero():
    employee = verify_employee(FakeSdk, _request("sso=valid"))
    assert employee is not None
    assert (
        employee.employee_id == "00123" and employee.department == "데이터팀"
    )


def test_verify_employee_without_cookie():
    assert verify_employee(FakeSdk, _request()) is None
    assert verify_employee(FakeSdk, _request("sso=expired")) is None


def test_login_url_replaces_client_origin_with_callback():
    url = login_url(
        FakeSdk,
        _request(query=b"ORIGIN=https://evil.example"),
        "https://api/cb/1",
    )
    assert url.endswith("ORIGIN=https://api/cb/1")


def test_lab_url_uses_a_workspace_per_employee():
    from core.config import Settings
    from core.notebook_links import lab_url

    settings = Settings(
        notebook_lab_base_url="https://lab.example/",
        notebook_lab_path_prefix="pv",
    )
    url = lab_url(settings, "users/u1/a b/execution.ipynb", "00123")
    assert (
        url
        == "https://lab.example/lab/workspaces/agentic-00123/tree/pv/users/u1/a%20b/execution.ipynb"
    )
    assert lab_url(Settings(notebook_lab_base_url=""), "x.ipynb", "1") is None


def test_sdk_request_has_flask_attributes():
    from api_service.auth.sdk import SdkRequest

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/svc/api/v1/auth/login/sso",
            "root_path": "/svc",
            "query_string": b"return_to=/",
            "headers": [(b"host", b"api.corp"), (b"cookie", b"a=1; b=2")],
            "server": ("api", 443),
            "client": ("10.0.0.1", 5000),
            "scheme": "https",
        }
    )
    view = SdkRequest(request, "https://api.corp/cb/1")
    assert view.host == "api.corp"
    assert view.host_url == "https://api.corp/"
    assert view.full_path == "/svc/api/v1/auth/login/sso?return_to=/"
    assert view.remote_addr == "10.0.0.1"
    assert view.environ["PATH_INFO"] == "/api/v1/auth/login/sso"
    assert view.environ["SCRIPT_NAME"] == "/svc"
    assert view.environ["HTTP_HOST"] == "api.corp"
    assert view.environ["REMOTE_ADDR"] == "10.0.0.1"
    assert view.cookies.to_dict() == {"a": "1", "b": "2"}
    assert view.args.to_dict()["ORIGIN"] == "https://api.corp/cb/1"
    # anything else falls through to the ASGI request
    assert view.query_params["return_to"] == "/"


def test_company_sso_draft_names_the_factory():
    import ast
    from pathlib import Path

    tree = ast.parse(
        (Path(__file__).parents[1] / "src/company_sso.py").read_text("utf-8")
    )
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "create_sdk" in names


def test_company_sso_userinfo_check(monkeypatch):
    import httpx

    import company_sso

    sent = {}

    def fake_get(url, cookies, timeout, follow_redirects):
        sent.update(cookies)
        return httpx.Response(
            200, json={"empNo": 123, "empName": "홍길동", "email": None}
        )

    monkeypatch.setattr(company_sso.httpx, "get", fake_get)
    cookie = "SMSESSION=s; AMTOKEN=a; GWP_LANGUAGE_ID=ko"
    employee = verify_employee(company_sso.create_sdk, _request(cookie))
    assert employee is not None
    assert (employee.employee_id, employee.name) == ("123", "홍길동")
    assert sent == {"SMSESSION": "s", "AMTOKEN": "a"}

    assert (
        verify_employee(company_sso.create_sdk, _request("AMTOKEN=a")) is None
    )
    logged_out = "SMOFC=logout; SMSESSION=s; AMTOKEN=a"
    assert (
        verify_employee(company_sso.create_sdk, _request(logged_out)) is None
    )

    url = login_url(company_sso.create_sdk, _request(), "https://api/cb/1")
    assert url == company_sso.SSO_LOGIN_PAGE + "?TARGET=https://api/cb/1"
