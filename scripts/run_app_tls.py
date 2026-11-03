"""Runs the gaia template's ``app.py`` over https, from the repo root::

    uv run python scripts/run_app_tls.py <key.pem> <cert.pem>

``GaiaService.main()`` calls ``uvicorn.run`` without TLS options, so this
wraps ``uvicorn.run`` to add them and then runs ``app.py`` as
``python app.py`` would. Everything else (the gaia routers, its
``custom_openapi``, Instrumentor, lifespan, ``config.PORT``) stays the
template's own. Used by ``scripts/run_local_https.ps1``.
"""

import runpy
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("usage: run_app_tls.py <key.pem> <cert.pem>")
    key, cert = sys.argv[1], sys.argv[2]
    serve = uvicorn.run

    def run_tls(app, *args, **kwargs):
        kwargs.setdefault("ssl_keyfile", key)
        kwargs.setdefault("ssl_certfile", cert)
        print(f"https on port {kwargs.get('port', 8000)}", flush=True)
        return serve(app, *args, **kwargs)

    uvicorn.run = run_tls  # gaia imports uvicorn after this
    sys.argv = [str(ROOT / "app.py")]
    sys.path[0] = str(ROOT)  # as `python app.py`: src.dtest importable
    runpy.run_path(str(ROOT / "app.py"), run_name="__main__")


if __name__ == "__main__":
    main()
