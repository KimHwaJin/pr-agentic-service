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
    assert lab_url(Settings(), "x.ipynb", "1") is None
