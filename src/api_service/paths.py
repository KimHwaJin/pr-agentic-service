"""Our paths, and middleware that runs only on them.

Inside the company network the app is the gaia template's, shared with
its own APIs (``/{workflow}/api/completion``, ``/api/admin/appReady``,
``/api/common/...``). Nothing of ours (request id, body limit, CORS,
audit, error shape) may touch those, so every middleware ``mount_api``
adds goes through ``OwnPaths``, and the error handlers check ``is_own``.
"""

import logging
from typing import Any

from starlette.middleware import Middleware
from starlette.types import ASGIApp, Receive, Scope, Send

from api_service import API_PREFIX

log = logging.getLogger(__name__)

OWN_PREFIXES = (API_PREFIX + "/", "/view/", "/dev/")


def is_own(path: str) -> bool:
    """``/api/v1/...``, ``/view/...``, ``/dev`` and below."""
    return path.startswith(OWN_PREFIXES) or path + "/" in OWN_PREFIXES


class OwnPaths:
    """Runs ``middleware`` for requests to our paths; anything else
    (other paths, lifespan) goes straight to the app::

        app.add_middleware(OwnPaths, middleware=BodyLimit, max_bytes=1024)
    """

    def __init__(self, app: ASGIApp, middleware: Any, **options: Any):
        self.app = app
        self.own: ASGIApp = middleware(app, **options)

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] in {"http", "websocket"} and is_own(scope["path"]):
            await self.own(scope, receive, send)
        else:
            await self.app(scope, receive, send)


class NotOwnPaths:
    """The inverse of ``OwnPaths``: runs ``middleware`` for every request
    except those to our paths, which go straight to the app."""

    def __init__(self, app: ASGIApp, middleware: Any, *args: Any, **kw: Any):
        self.app = app
        self.other: ASGIApp = middleware(app, *args, **kw)

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] in {"http", "websocket"} and is_own(scope["path"]):
            await self.app(scope, receive, send)
        else:
            await self.other(scope, receive, send)


# The gaia template's access key check (gaia/core.py ``AuthMiddleware``,
# on from GAIA_DEPLOYMENT=development up, header ``accesskey``). It guards
# the template's APIs; ours have their own SSO login and API keys, and a
# browser opening /dev/ or /view/ has no way to send the key.
GAIA_AUTH = "AuthMiddleware"


def _is_gaia_auth(cls: Any) -> bool:
    module = getattr(cls, "__module__", "") or ""
    return getattr(cls, "__name__", "") == GAIA_AUTH and (
        module == "gaia" or module.startswith("gaia.") or ".gaia." in module
    )


def skip_gaia_auth(app: Any) -> None:
    """Keeps the gaia template's access key check off our paths.

    The template may add its middleware any time before serving (in
    ``GaiaService()`` or in ``main()``), so the swap happens when the app
    builds its middleware stack, on the first ASGI call. Outside the
    company network there is no such middleware and nothing changes.
    """
    build = app.build_middleware_stack

    def build_middleware_stack():
        swapped = 0
        for i, entry in enumerate(app.user_middleware):
            if _is_gaia_auth(entry.cls):
                app.user_middleware[i] = Middleware(
                    NotOwnPaths, entry.cls, *entry.args, **entry.kwargs
                )
                swapped += 1
        if swapped:
            log.info(
                "gaia_auth_skipped_on_own_paths prefixes=%s",
                ",".join(OWN_PREFIXES),
            )
        return build()

    app.build_middleware_stack = build_middleware_stack
