"""Corporate SSO SDK hookup (draft; fill in inside the closed network).

Loaded by ``SSO_ADAPTER=company`` through
``SSO_ADAPTER_FACTORY=company_sso:create_sdk``. Only this file touches the
private SDK; see ``api_service/auth/sdk.py`` for what we expect from it.

What to change here:
1. The import below: the SDK's real module path (same as the Flask sample).
2. ``create_sdk``: construct the SDK the way the Flask sample does. If the
   sample passes a return URL some other way than ``request.args["ORIGIN"]``
   (a constructor argument, an attribute), pass ``callback_url`` that way.

Do not log or print cookies, SDK URLs or employee data here.
"""

# The import fails at startup when the module is missing, which is what we
# want with SSO_ADAPTER=company.
from your_private_module import SSO  # ty: ignore[unresolved-import]


def create_sdk(request, callback_url):
    """Return a fresh SDK instance for one request.

    ``request`` is a read-only Flask-like view (``args``, ``cookies``,
    ``environ``, ``url``, ``headers``, ``host``, ``path``, ...).
    ``callback_url`` is set only when building the login URL; it is already
    in ``request.args["ORIGIN"]``. ``None`` when verifying a cookie.
    """
    return SSO(request)
