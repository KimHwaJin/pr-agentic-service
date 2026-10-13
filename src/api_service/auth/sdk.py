"""Boundary to the corporate SSO SDK (closed network only, synchronous, Flask style).

Known SDK contract (Flask sample): ``sso = SSO(request)``, ``sso.redirect_url``,
``sso.check_day_cookie(cookie) -> bool``, ``sso.get_sso_info(cookie)`` returning
(employee_no, name, english_name, department, email). The SDK reads ``request.url``,
``request.args.to_dict()``, ``request.cookies.to_dict()`` and ``request.environ``; we give
it a read-only view of the ASGI request instead of Flask.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import Request
from starlette.datastructures import QueryParams


@dataclass(frozen=True)
class Employee:
    employee_id: str
    name: str
    english_name: str | None = None
    department: str | None = None
    email: str | None = None


class CompanySdk(Protocol):
    redirect_url: str

    def check_day_cookie(self, cookie: str) -> bool: ...

    def get_sso_info(self, cookie: str) -> Any: ...


# factory(request_view, callback_url | None) -> SDK instance, e.g. ``lambda r, _: SSO(r)``
SdkFactory = Callable[[Any, str | None], CompanySdk]


class _Values(Mapping[str, str]):
    def __init__(self, items: Iterable[tuple[str, str]]):
        self._values: dict[str, list[str]] = {}
        for key, value in items:
            self._values.setdefault(key, []).append(value)

    def __getitem__(self, key: str) -> str:
        return self._values[key][0]

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def to_dict(self, flat: bool = True) -> dict[str, Any]:
        return {k: v[0] if flat else list(v) for k, v in self._values.items()}


def _environ(request: Request) -> dict[str, str]:
    scope = request.scope
    server = scope.get("server")
    environ = {
        "REQUEST_METHOD": scope.get("method", "GET"),
        "SCRIPT_NAME": scope.get("root_path", ""),
        "PATH_INFO": scope.get("path", ""),
        "QUERY_STRING": scope.get("query_string", b"").decode("latin-1"),
        "SERVER_NAME": server[0] if server else "",
        "SERVER_PORT": str(server[1]) if server and server[1] else "",
        "wsgi.url_scheme": scope.get("scheme", "http"),
    }
    for name, value in scope.get("headers", []):
        header = name.decode("latin-1").upper().replace("-", "_")
        key = header if header in {"CONTENT_TYPE", "CONTENT_LENGTH"} else "HTTP_" + header
        text = value.decode("latin-1")
        environ[key] = environ[key] + ("; " if key == "HTTP_COOKIE" else ",") + text if key in environ else text
    return environ


class SdkRequest:
    """Flask-like read-only request. On login, args ORIGIN is the server callback."""

    def __init__(self, request: Request, callback_url: str | None = None):
        params = request.query_params
        if callback_url is not None:
            params = QueryParams(
                [(k, v) for k, v in params.multi_items() if k != "ORIGIN"] + [("ORIGIN", callback_url)]
            )
        self.args = _Values(params.multi_items())
        self.cookies = _Values(request.cookies.items())
        self.environ = _environ(request)
        self.url = str(request.url)
        self.headers = request.headers
        self.method = request.method


def verify_employee(sdk_factory: SdkFactory, request: Request) -> Employee | None:
    cookie = request.headers.get("cookie")
    if not cookie:
        return None
    sdk = sdk_factory(SdkRequest(request), None)
    valid = sdk.check_day_cookie(cookie)
    if valid is False:
        return None
    if valid is not True:
        raise ValueError("Invalid SSO verification response")
    info = sdk.get_sso_info(cookie)
    if not isinstance(info, (tuple, list)) or len(info) != 5:
        raise ValueError("Invalid SSO employee response")
    employee_id, name, english_name, department, email = info
    if not isinstance(employee_id, str) or not employee_id.strip() or not isinstance(name, str):
        raise ValueError("Invalid SSO employee response")
    return Employee(employee_id.strip(), name, english_name, department, email)


def login_url(sdk_factory: SdkFactory, request: Request, callback_url: str) -> str:
    return sdk_factory(SdkRequest(request, callback_url), callback_url).redirect_url
