"""IdP (SSO) hookup (fill in inside the closed network).

Loaded by ``SSO_ADAPTER=idp`` through
``SSO_ADAPTER_FACTORY=idp_login:create_sdk``. ``create_sdk`` returns an
object with ``redirect_url``, ``check_day_cookie(cookie)`` and
``get_sso_info(cookie)``; see ``api_service/auth/sdk.py``.

Two ways to verify, picked by ``VERIFY_WITH``:
- ``"userinfo"`` (the Streamlit sample): send the SMSESSION and AMTOKEN
  cookies to the workplace userinfo API and read the employee from its JSON.
  No private SDK needed.
- ``"sdk"`` (the Flask sample): the private SDK's ``check_day_cookie`` and
  ``get_sso_info``.

Login goes to ``SSO_LOGIN_PAGE?TARGET=<our page>`` (userinfo) or to
the SDK's own ``redirect_url`` (sdk: the workplace token page, which comes
back to our root ``/``); its origin must be in SSO_ALLOWED_ORIGINS.

Do not log or print cookies, URLs with tickets or employee data here.
"""

import logging

import httpx

log = logging.getLogger(__name__)

VERIFY_WITH = "userinfo"  # or "sdk"

SSO_LOGIN_PAGE = "https://idp.example.com/sso/am/login.jsp"

# What SSO_LOGIN_PAGE gets as TARGET. "page" (the Streamlit sample's
# TARGET={your_page_url}): our service page, ``https://<service>/``; the
# SSO comes back there and our root goes on to the callback. "callback":
# our callback URL itself.
LOGIN_TARGET = "page"

# userinfo: a browser with an SMSESSION but no AMTOKEN (a fresh or incognito
# window after the SSO login: only the workplace issues it) is sent to the
# workplace token page instead of SSO_LOGIN_PAGE,
# ``TOKEN_PAGE?client_id=<service>&redirect_url=<service>``; it issues the
# AMTOKEN and returns to our root ``/``, which
# goes on to the callback. Its origin must be in SSO_ALLOWED_ORIGINS.
# Empty: SSO_LOGIN_PAGE as before.
TOKEN_PAGE = ""
# Its query, filled with our service ({service}); the page refuses a wrong
# name as an expired session. SSO_CHECK_URL, when set, makes this moot.
TOKEN_PAGE_QUERY = "client_id={service}&redirect_uri={service}"
# The workplace check the SDK makes (``.../api/common/v1/auth/sso``): asked
# with the browser's cookies, it answers 401 {"url": <token page URL>}, the
# exact URL to send the browser to. Set: used before TOKEN_PAGE.
SSO_CHECK_URL = ""

# Our service as the SSO registered it: the SDK's ORIGIN (the URL it asks
# the workplace about) and the token page's client_id/redirect_url.
# Empty: the Host header alone (``host``, no scheme), the form our
# registration answers; the SDK's own fallback
# (``https://host``) and our callback URL get errorcode=404.
SERVICE_URL = ""
USERINFO_URL = "http://workplace.example.com/api/common/v1/auth/userInfo"
USERINFO_TIMEOUT_SECONDS = 5.0

# Where the employee fields are in the userinfo JSON, as dotted paths
# (e.g. "data.empNo"). Change only the right side; drop a line the JSON
# does not have (employee_id and name are required). When a required field
# is missing the app logs the JSON's key names (not values).
FIELDS = {
    "employee_id": "empNo",
    "name": "empName",
    "english_name": "empNameEn",
    "department": "deptName",
    "email": "email",
}


def create_sdk(request, callback_url):
    """Return a fresh verifier for one request.

    ``request`` is a read-only Flask-like view (``args``, ``cookies``,
    ``environ``, ``url``, ``headers``, ...). ``callback_url`` is set only
    when building the login URL; ``None`` when verifying.
    """
    if VERIFY_WITH == "sdk":
        # the private SDK, as in the Flask sample
        from your_private_module import SSO  # ty: ignore[unresolved-import]

        # the SDK takes ORIGIN, when there is one, as the service URL it
        # sends the workplace (URL=..., Client-Url) and gets back from the
        # token page; it must be the registered one, never our callback
        origin = _service(request)
        request.args = type(request.args)(
            [*request.args.to_dict().items(), ("ORIGIN", origin)]
        )
        sso = SSO(request)
        # what the SDK really sent the workplace (its private fields; host
        # names only, no cookie): the one line that settles a 404
        name = type(sso).__name__
        log.info(
            "sso_sdk origin=%s target_url=%s protocol=%s uuid=%s",
            origin,
            getattr(sso, f"_{name}__target_url", "?"),
            getattr(sso, f"_{name}__protocol", "?"),
            bool(getattr(sso, "uuid", False)),
        )
    else:
        sso = UserinfoCheck(request)
    if callback_url is not None and VERIFY_WITH != "sdk":
        cookies = request.cookies
        token_url = (
            _token_url(request)
            if cookies.get("SMSESSION") and not cookies.get("AMTOKEN")
            else None
        )
        if token_url:
            # logged in to the SSO (no SMSESSION: SSO_LOGIN_PAGE first;
            # the token page refuses it as an expired session)
            sso.redirect_url = token_url
        else:
            # the callback has no query, so it goes in as is, like the sample
            sso.redirect_url = (
                f"{SSO_LOGIN_PAGE}?TARGET={_target(request, callback_url)}"
            )
    # sdk: the SDK's own URL (the workplace's token page, which issues the
    # AMTOKEN and returns to our registered host, that is GET /); its origin
    # must be in SSO_ALLOWED_ORIGINS
    return sso


def _token_url(request):
    """Where a browser with an SMSESSION gets its AMTOKEN, or None."""
    service = _service(request)
    if SSO_CHECK_URL:
        response = None
        try:
            response = httpx.get(
                SSO_CHECK_URL,
                params={"URL": service},
                headers={"Client-Url": service},
                cookies=request.cookies.to_dict(),
                timeout=USERINFO_TIMEOUT_SECONDS,
            )
            url = (
                response.json().get("url")
                if response.status_code == 401
                else None
            )
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            log.warning("sso_check failed error_type=%s", type(exc).__name__)
            url = None
        # the path only: the query may carry tokens
        log.info(
            "sso_check status=%s url=%s",
            getattr(response, "status_code", "-"),
            httpx.URL(url).path if isinstance(url, str) else "-",
        )
        if isinstance(url, str) and url:
            return url
    if TOKEN_PAGE:
        return f"{TOKEN_PAGE}?" + TOKEN_PAGE_QUERY.format(service=service)
    return None


def _target(request, callback_url):
    """SSO_LOGIN_PAGE's TARGET (see LOGIN_TARGET)."""
    if LOGIN_TARGET != "page":
        return callback_url
    service = _service(request)
    if "://" in service:
        return service.rstrip("/") + "/"
    scheme = getattr(request, "scheme", "") or "https"
    return f"{scheme}://{service}/"


def _service(request):
    """Our service as the SSO registered it (SERVICE_URL, else the Host)."""
    return SERVICE_URL or request.environ.get("HTTP_HOST", "")


class UserinfoCheck:
    """The Streamlit sample's check: ask workplace whose cookies these are."""

    def __init__(self, request):
        self.cookies = request.cookies.to_dict()
        self.redirect_url = SSO_LOGIN_PAGE
        self._info = None

    def check_day_cookie(self, cookie) -> bool:
        if self.cookies.get("SMOFC") == "logout":
            log.info("sso_userinfo result=logged_out")
            return False
        sent = {
            name: self.cookies[name]
            for name in ("SMSESSION", "AMTOKEN")
            if self.cookies.get(name)
        }
        if len(sent) < 2:
            log.info("sso_userinfo result=missing cookies=%s", sorted(sent))
            return False
        response = httpx.get(
            USERINFO_URL,
            cookies=sent,
            timeout=USERINFO_TIMEOUT_SECONDS,
            # requests (the sample) follows redirects; httpx does not
            follow_redirects=True,
        )
        if response.status_code != 200:
            log.info("sso_userinfo result=http_%s", response.status_code)
            return False
        try:
            data = response.json()
        except ValueError:
            log.warning("sso_userinfo result=not_json")
            return False
        unknown = set(FIELDS) - set(_OUR_FIELDS)
        if unknown:
            # only the paths (right side) change; the names stay ours
            log.warning("sso_userinfo bad_fields names=%s", sorted(unknown))
            return False
        info = {key: _pick(data, path) for key, path in FIELDS.items()}
        if not isinstance(info.get("employee_id"), str) or not isinstance(
            info.get("name"), str
        ):
            # key names only, to fill FIELDS
            log.warning("sso_userinfo result=no_employee keys=%s", _keys(data))
            return False
        self._info = info
        return True

    def get_sso_info(self, cookie):
        info = self._info or {}
        return tuple(
            None if info.get(key) is None else str(info[key])
            for key in _OUR_FIELDS
        )


_OUR_FIELDS = ("employee_id", "name", "english_name", "department", "email")


def _pick(data, path):
    for part in path.split("."):
        if not isinstance(data, dict):
            return None
        data = data.get(part)
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        return str(data)
    return data


def _keys(data, prefix="", depth=0):
    if not isinstance(data, dict) or depth > 2:
        return []
    out = []
    for key, value in data.items():
        out.append(prefix + str(key))
        out += _keys(value, f"{prefix}{key}.", depth + 1)
    return out
