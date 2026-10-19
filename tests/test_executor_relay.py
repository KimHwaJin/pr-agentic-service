import json
from types import SimpleNamespace
from typing import Any, cast

from api_service.routers.executor import _as_user, _match

E = "674ff370-c4c6-42c4-a423-eba72d18352b"


def _access(method: str, path: str) -> str | None:
    route = _match(method, path)
    return route[0] if route else None


def test_only_listed_routes_are_relayed():
    assert _access("GET", "executions") == "list"
    route = _match("GET", f"executions/{E}/steps")
    assert route and route[0] == "execution" and route[1]["execution"] == E
    assert _access("GET", f"executions/{E}/attempts") == "admin"
    assert _access("POST", "runtime-targets") == "admin"
    assert _access("POST", f"runtime-targets/{E}/drain") == "admin"
    assert _access("POST", "maintenance/drain") == "admin"
    for method, path in [
        ("POST", "executions"),
        ("POST", f"executions/{E}/cancel"),
        ("GET", f"executions/{E}/../../maintenance"),
        ("GET", "executions/not-a-uuid"),
    ]:
        assert _match(method, path) is None


def test_runtime_registration_is_recorded_as_the_admin():
    user = cast(Any, SimpleNamespace(id="u-1"))
    body = _as_user(
        json.dumps({"name": "x", "actor": {"id": "spoof"}}).encode(), user
    )
    assert json.loads(body)["actor"] == {"type": "USER", "id": "u-1"}
