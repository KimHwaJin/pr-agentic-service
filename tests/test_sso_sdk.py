from fastapi import Request

from src.dtest.api_service.auth.sdk import login_url, verify_employee


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
    from src.dtest.core.config import Settings
    from src.dtest.core.notebook_links import lab_url

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
    from src.dtest.api_service.auth.sdk import SdkRequest

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

    path = Path(__file__).parents[1] / "src/dtest/company_sso.py"
    tree = ast.parse(path.read_text("utf-8"))
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "create_sdk" in names
