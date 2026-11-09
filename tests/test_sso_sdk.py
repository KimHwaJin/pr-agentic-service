from fastapi import Request

from api_service.auth.sdk import entry_url, verify_employee


def _request(cookie: str | None = None, query: bytes = b"") -> Request:
    headers = [(b"host", b"api")]
    headers += [(b"cookie", cookie.encode())] if cookie else []
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
        self.args = request.args.to_dict()
        self.redirect_url = (
            "https://sso.example/login?TARGET=" + callback if callback else ""
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


def test_login_drops_a_client_origin():
    seen = []

    def make(request, callback):
        seen.append(request.args.to_dict())
        return FakeSdk(request, callback)

    url = entry_url(
        make,
        _request(query=b"ORIGIN=https://evil.example&x=1"),
        "https://api/cb/1",
    )
    assert url.endswith("TARGET=https://api/cb/1")
    assert seen == [{"x": "1"}]


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
    assert "ORIGIN" not in view.args.to_dict()
    # anything else falls through to the ASGI request
    assert view.query_params["return_to"] == "/"


def test_idp_login_draft_names_the_factory():
    import ast
    from pathlib import Path

    tree = ast.parse(
        (Path(__file__).parents[1] / "src/idp_login.py").read_text("utf-8")
    )
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "create_sdk" in names


def test_idp_login_userinfo_check(monkeypatch):
    import httpx

    import idp_login

    sent = {}

    def fake_get(url, cookies, timeout, follow_redirects):
        sent.update(cookies)
        return httpx.Response(
            200, json={"empNo": 123, "empName": "홍길동", "email": None}
        )

    monkeypatch.setattr(idp_login.httpx, "get", fake_get)
    cookie = "SMSESSION=s; AMTOKEN=a; GWP_LANGUAGE_ID=ko"
    employee = verify_employee(idp_login.create_sdk, _request(cookie))
    assert employee is not None
    assert (employee.employee_id, employee.name) == ("123", "홍길동")
    assert sent == {"SMSESSION": "s", "AMTOKEN": "a"}

    assert verify_employee(idp_login.create_sdk, _request("AMTOKEN=a")) is None
    logged_out = "SMOFC=logout; SMSESSION=s; AMTOKEN=a"
    assert verify_employee(idp_login.create_sdk, _request(logged_out)) is None

    url = entry_url(idp_login.create_sdk, _request(), "https://api/cb/1")
    assert url == idp_login.SSO_LOGIN_PAGE + "?TARGET=https://api/cb/1"


def test_idp_login_sdk_mode_gives_the_registered_origin(monkeypatch):
    import sys
    import types

    import idp_login

    seen = {}

    class SSO:
        def __init__(self, request):
            seen["origin"] = request.args.to_dict().get("ORIGIN")
            self.redirect_url = ""

        def check_day_cookie(self, cookie):
            return False

    monkeypatch.setitem(
        sys.modules, "your_private_module", types.SimpleNamespace(SSO=SSO)
    )
    monkeypatch.setattr(idp_login, "VERIFY_WITH", "sdk")
    assert verify_employee(idp_login.create_sdk, _request("a=1")) is None
    # the bare host, as the SSO registered it; not a URL of ours
    assert seen["origin"] == "api"
    monkeypatch.setattr(idp_login, "SERVICE_URL", "https://api")
    entry_url(idp_login.create_sdk, _request(), "https://api/cb/1")
    assert seen["origin"] == "https://api"


def test_sdk_request_shows_the_public_scheme_behind_the_ingress():
    """TLS ends at the ingress: the pod gets http, the SDK must see https
    (it sends the bare host to the SSO only for https requests)."""
    from api_service.auth.sdk import SdkRequest

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/auth/login/sso/callback/f1",
            "query_string": b"",
            "headers": [(b"host", b"agentic.corp")],
            "server": ("10.1.2.3", 8080),
            "scheme": "http",
        }
    )
    view = SdkRequest(request, scheme="https")
    assert view.url.startswith("https://agentic.corp/")
    assert view.host_url == "https://agentic.corp/"
    assert view.url_root == "https://agentic.corp/"
    assert view.environ["wsgi.url_scheme"] == "https"
    assert view.environ["HTTP_HOST"] == "agentic.corp"
    # without a public scheme the pod's own is kept
    assert SdkRequest(request).url.startswith("http://agentic.corp/")


def test_idp_adapter_takes_the_scheme_of_the_public_origin(monkeypatch):
    import sys
    import types

    from api_service.auth import adapters
    from core.config import Settings

    seen = []
    module = types.ModuleType("fake_idp_sdk")
    module.make = lambda r, cb: seen.append(r.url) or FakeSdk(r, cb)
    monkeypatch.setitem(sys.modules, "fake_idp_sdk", module)
    settings = Settings(
        sso_adapter="idp",
        sso_adapter_factory="fake_idp_sdk:make",
        public_api_origin="https://agentic.corp",
    )
    adapter = adapters.load_adapter(settings)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/x",
            "query_string": b"",
            "headers": [(b"host", b"agentic.corp"), (b"cookie", b"sso=valid")],
            "server": ("10.1.2.3", 8080),
            "scheme": "http",
        }
    )
    adapter._verify(request)
    assert seen == ["https://agentic.corp/x"]


def test_a_rejection_logs_the_service_url_and_the_sso_answer(caplog):
    class Refused(FakeSdk):
        def __init__(self, request, callback):
            super().__init__(request, callback)
            self.redirect_url = (
                "https://login.corp/sso/SSOServiceInformation.jsp"
                "?errorcode=404&token=secret"
            )

        def check_day_cookie(self, cookie):
            return False

    caplog.set_level("INFO")
    assert verify_employee(Refused, _request("SMSESSION=x"), "https") is None
    line = caplog.messages[-1]
    assert "scheme=https" in line and "cookies=SMSESSION" in line
    assert "login.corp/sso/SSOServiceInformation.jsp?errorcode=404" in line
    assert "secret" not in line and "SMSESSION=x" not in line


def test_idp_login_sdk_mode_logs_what_the_sdk_sent(monkeypatch, caplog):
    import sys
    import types

    import idp_login

    class SSO:
        def __init__(self, request):
            self.__target_url = request.args.to_dict()["ORIGIN"]
            self.__protocol = "https://"
            self.uuid = False
            self.redirect_url = ""

        def check_day_cookie(self, cookie):
            return False

    monkeypatch.setitem(
        sys.modules, "your_private_module", types.SimpleNamespace(SSO=SSO)
    )
    monkeypatch.setattr(idp_login, "VERIFY_WITH", "sdk")
    caplog.set_level("INFO")
    verify_employee(idp_login.create_sdk, _request("SMSESSION=x"))
    line = next(m for m in caplog.messages if m.startswith("sso_sdk "))
    assert "origin=api target_url=api protocol=https:// uuid=False" in line
    assert "SMSESSION" not in line
