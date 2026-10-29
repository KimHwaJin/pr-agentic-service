import asyncio
import json
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api_service.errors import ApiError
from api_service.routers import executor as relay
from api_service.routers.executor import _as_user, _match
from api_service.services.api_clients import Caller
from core.config import Settings
from core.executor.client import ExecutorClient

E = "674ff370-c4c6-42c4-a423-eba72d18352b"


def _access(method: str, path: str) -> tuple[Any, bool] | None:
    route = _match(method, path)
    return route[1:] if route else None


def test_browser_routes():
    assert _access("GET", "executions") == ("list", True)
    route = _match("GET", f"executions/{E}/steps")
    assert route and route[1] == "execution" and route[0]["execution"] == E
    assert _access("GET", f"executions/{E}/attempts") == ("admin", True)
    assert _access("POST", "runtime-targets") == ("ops", False)
    assert _access("POST", f"runtime-targets/{E}/drain") == ("ops", False)
    assert _access("POST", "maintenance/drain") == ("ops", False)
    for method, path in [
        ("GET", f"executions/{E}/../../maintenance"),
        ("GET", "executions/not-a-uuid"),
        ("DELETE", f"executions/{E}"),
    ]:
        assert _match(method, path) is None


def test_key_callers_may_write_but_not_operate():
    for method, path in [
        ("POST", "executions"),
        ("POST", f"executions/{E}/operations"),
        ("POST", f"executions/{E}/finalize"),
        ("POST", f"executions/{E}/cancel"),
        ("POST", f"executions/{E}/retry"),
        ("POST", f"executions/{E}/artifacts"),
        ("GET", f"artifacts/{E}/content"),
        ("GET", f"executions/{E}/notebook/cells/3"),
    ]:
        route = _access(method, path)
        assert route is not None and route[1] is True, path
        assert route[0] is None or method == "GET"  # browser: reads only
    for path in [
        f"executions/{E}/diagnostics",
        "runtime-targets",
        "runtime-pools",
        "maintenance",
    ]:
        route = _access("GET", path)
        assert route is not None and route[1] is False


def test_runtime_registration_is_recorded_as_the_admin():
    user = cast(Any, SimpleNamespace(id="u-1"))
    body = _as_user(
        json.dumps({"name": "x", "actor": {"id": "spoof"}}).encode(), user
    )
    assert json.loads(body)["actor"] == {"type": "USER", "id": "u-1"}


# --- forwarding ------------------------------------------------------------


def _services(
    sent: list[httpx.Request], admin_key: str = "", api_key: str = "exe_ours"
):
    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"ok": True})

    executor = ExecutorClient(
        "http://executor", 5, api_key, admin_key, "pr-agentic"
    )
    executor.http = httpx.AsyncClient(
        base_url="http://executor/api/v1",
        transport=httpx.MockTransport(handle),
    )
    return SimpleNamespace(
        settings=Settings(executor_tenant_id="pr-agentic"), executor=executor
    )


def _request(method: str, path: str, headers: dict[str, str], body=b""):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": method,
            "path": f"/api/v1/executor/{path}",
            "query_string": b"limit=5",
            "headers": [
                (k.lower().encode(), v.encode()) for k, v in headers.items()
            ],
        },
        receive,
    )


def _as_caller(services, method, path, headers, body=b"", tenant="partner"):
    caller = Caller("c-1", "partner-agent", tenant)
    user = SimpleNamespace(id="u-1", role="user")
    response = asyncio.run(
        relay._for_caller(
            cast(Any, services),
            _request(method, path, headers, body),
            path,
            caller,
            cast(Any, user),
        )
    )
    return response


def test_key_caller_goes_as_its_tenant_with_our_key():
    sent: list[httpx.Request] = []
    body = json.dumps({"idempotency_key": "k"}).encode()
    response = _as_caller(
        _services(sent),
        "POST",
        "executions",
        {
            "X-Api-Key": "pas_live_theirs",
            "X-Tenant-Id": "someone-else",
            "X-Project-Id": "their-project",
            "X-Session-Id": "their-session",
            "Content-Type": "application/json",
        },
        body,
    )
    assert response.status_code == 200
    headers = sent[0].headers
    assert headers["x-api-key"] == "exe_ours"
    assert headers["x-tenant-id"] == "partner"
    assert headers["x-user-id"] == "u-1"
    # another tenant's project is its own: passed on after a form check
    assert headers["x-project-id"] == "their-project"
    assert headers["x-session-id"] == "their-session"
    assert sent[0].content == body
    assert sent[0].url.params["limit"] == "5"


def test_key_caller_of_our_tenant_needs_project_membership(monkeypatch):
    async def not_member(services, user, project_id, write=False):
        raise HTTPException(404, "Project not found.")

    monkeypatch.setattr(relay, "project_for", not_member)
    with pytest.raises(HTTPException) as err:
        _as_caller(
            _services([]),
            "GET",
            "executions",
            {"X-Project-Id": "someone-elses"},
            tenant="pr-agentic",
        )
    assert err.value.status_code == 404


def test_operator_routes_need_the_operator_key():
    match = _match("GET", "runtime-targets")
    assert match is not None
    admin = cast(Any, SimpleNamespace(id="a-1", role="admin"))
    with pytest.raises(ApiError) as err:
        asyncio.run(
            relay._for_user(
                cast(Any, _services([])),
                _request("GET", "runtime-targets", {}),
                "runtime-targets",
                match,
                admin,
            )
        )
    assert err.value.status == 503
    sent: list[httpx.Request] = []
    asyncio.run(
        relay._for_user(
            cast(Any, _services(sent, admin_key="exe_ops")),
            _request("GET", "runtime-targets", {}),
            "runtime-targets",
            match,
            admin,
        )
    )
    assert sent[0].headers["x-api-key"] == "exe_ops"
    assert sent[0].headers["x-user-id"] == "a-1"
    assert "x-tenant-id" not in sent[0].headers
    # an executor in header mode (no keys at all): no key, still allowed
    sent.clear()
    asyncio.run(
        relay._for_user(
            cast(Any, _services(sent, api_key="")),
            _request("GET", "runtime-targets", {}),
            "runtime-targets",
            match,
            admin,
        )
    )
    assert "x-api-key" not in sent[0].headers


def test_browser_list_is_scoped_by_the_user_header(monkeypatch):
    async def member(services, user, params):
        return None

    monkeypatch.setattr(relay, "scope_execution_list", member)
    match = _match("GET", "executions")
    assert match is not None
    sent: list[httpx.Request] = []
    user = cast(Any, SimpleNamespace(id="u-9", role="user"))
    request = _request("GET", "executions", {"X-User-Id": "spoof"})
    request.scope["query_string"] = b"user_id=spoof&tenant_id=x&status=RUNNING"
    asyncio.run(
        relay._for_user(
            cast(Any, _services(sent)), request, "executions", match, user
        )
    )
    assert sent[0].headers["x-user-id"] == "u-9"
    assert dict(sent[0].url.params) == {"status": "RUNNING"}


def test_admin_user_filter_becomes_the_user_header():
    match = _match("GET", "executions")
    assert match is not None
    sent: list[httpx.Request] = []
    admin = cast(Any, SimpleNamespace(id="a-1", role="admin"))
    request = _request("GET", "executions", {})
    request.scope["query_string"] = b"user_id=U-7&trigger_type=INTERACTIVE"
    asyncio.run(
        relay._for_user(
            cast(Any, _services(sent)), request, "executions", match, admin
        )
    )
    assert sent[0].headers["x-user-id"] == "u-7"
    assert dict(sent[0].url.params) == {"trigger_type": "INTERACTIVE"}
