"""Corporate SSO hookup (draft; fill in inside the closed network).

Loaded by ``SSO_ADAPTER=company`` through
``SSO_ADAPTER_FACTORY=company_sso:create_sdk``. ``create_sdk`` returns an
object with ``redirect_url``, ``check_day_cookie(cookie)`` and
``get_sso_info(cookie)``; see ``api_service/auth/sdk.py``.

Two ways to verify, picked by ``VERIFY_WITH``:
- ``"userinfo"`` (the Streamlit sample): send the SMSESSION and AMTOKEN
  cookies to the workplace userinfo API and read the employee from its JSON.
  No private SDK needed.
- ``"sdk"`` (the Flask sample): the private SDK's ``check_day_cookie`` and
  ``get_sso_info``.

Login always goes to ``SSO_LOGIN_PAGE?TARGET=<our callback>``; its origin
must be in SSO_ALLOWED_ORIGINS.

Do not log or print cookies, URLs with tickets or employee data here.
"""

import logging

import httpx

log = logging.getLogger(__name__)

VERIFY_WITH = "userinfo"  # or "sdk"

SSO_LOGIN_PAGE = "https://company.com/sso/am/login.jsp"
USERINFO_URL = "http://workplace.company.com/api/common/v1/auth/userinfo"
USERINFO_TIMEOUT_SECONDS = 5.0

# Where the employee fields are in the userinfo JSON, as dotted paths
# (e.g. "data.empNo"). Placeholders until the real keys are known: the app
# logs the JSON's key names (not values) when a field is missing.
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

        sso = SSO(request)
    else:
        sso = UserinfoCheck(request)
    if callback_url is not None:
        # the callback has no query, so it goes in as is, like the sample
        sso.redirect_url = f"{SSO_LOGIN_PAGE}?TARGET={callback_url}"
    return sso


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
            USERINFO_URL, cookies=sent, timeout=USERINFO_TIMEOUT_SECONDS
        )
        if response.status_code != 200:
            log.info("sso_userinfo result=http_%s", response.status_code)
            return False
        try:
            data = response.json()
        except ValueError:
            log.warning("sso_userinfo result=not_json")
            return False
        info = {key: _pick(data, path) for key, path in FIELDS.items()}
        if not isinstance(info["employee_id"], str) or not isinstance(
            info["name"], str
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
            for key in (
                "employee_id",
                "name",
                "english_name",
                "department",
                "email",
            )
        )


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
