"""Our paths, and middleware that runs only on them.

Inside the company network the app is the gaia template's, shared with
its own APIs (``/{workflow}/api/completion``, ``/api/admin/appReady``,
``/api/common/...``). Nothing of ours (request id, body limit, CORS,
audit, error shape) may touch those, so every middleware ``mount_api``
adds goes through ``OwnPaths``, and the error handlers check ``is_own``.
"""

from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

from api_service import API_PREFIX

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
