from fastapi import Request

from api_service.auth.sdk import login_url, verify_employee


def _request(cookie: str | None = None, query: bytes = b"") -> Request:
    headers = [(b"cookie", cookie.encode())] if cookie else []
    return Request({"type": "http", "method": "GET", "path": "/login", "query_string": query, "headers": headers, "server": ("api", 443), "scheme": "https"})


class FakeSdk:
    def __init__(self, request, callback):
        self.request, self.callback = request, callback
        self.redirect_url = "https://sso.example/login?ORIGIN=" + request.args.to_dict()["ORIGIN"] if callback else ""

    def check_day_cookie(self, cookie):
        return "valid" in cookie

    def get_sso_info(self, cookie):
        return ("00123", "홍길동", "Hong", "데이터팀", "hong@example.com")


def test_verify_employee_keeps_leading_zero():
    employee = verify_employee(FakeSdk, _request("sso=valid"))
    assert employee.employee_id == "00123" and employee.department == "데이터팀"


def test_verify_employee_without_cookie():
    assert verify_employee(FakeSdk, _request()) is None
    assert verify_employee(FakeSdk, _request("sso=expired")) is None


def test_login_url_replaces_client_origin_with_callback():
    url = login_url(FakeSdk, _request(query=b"ORIGIN=https://evil.example"), "https://api/cb/1")
    assert url.endswith("ORIGIN=https://api/cb/1")
