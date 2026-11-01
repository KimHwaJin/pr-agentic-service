"""Callers with one of our keys (X-Api-Key + X-User-Id) and our calls out."""

import asyncio
import json
import logging
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api_service import deps
from api_service.errors import ApiError
from api_service.routers import batch
from api_service.services import api_clients
from core import batch_admin
from core.config import Settings
from core.logging_setup import SecretFilter
from core.models import ApiClient, User
from worker import executor_events

USER = "0c8a2f86-5d0e-4e55-9a3c-6f2f0f6a1b11"
KEY = "pas_dev_secret-value"


class _Db:
    def __init__(self, clients=(), users=()):
        self.clients = {c.key_sha256: c for c in clients}
        self.users = {u.id: u for u in users}

    def sessions(self):
        db = self

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def scalar(self, statement):
                params = statement.compile().params
                if "key_sha256_1" in params:
                    return db.clients.get(params["key_sha256_1"])
                wanted = params["lower_1"]  # employee id
                return next(
                    (
                        u
                        for u in db.users.values()
                        if u.employee_id.lower() == wanted
                    ),
                    None,
                )

            async def get(self, model, key):
                assert model is User
                return db.users.get(key)

            async def execute(self, statement):
                pass

            async def commit(self):
                pass

        return Session()


def _client(status="active", tenant="partner"):
    return ApiClient(
        id="c-1",
        name="partner-agent",
        tenant=tenant,
        key_prefix=KEY[:12],
        key_sha256=api_clients.digest(KEY),
        status=status,
    )


def _user(active=True, role="user"):
    return User(
        id=USER, employee_id="e1", name="n", role=role, is_active=active
    )


@pytest.fixture(autouse=True)
def _clean_caches():
    api_clients._cache.clear()
    deps._USER_CACHE.clear()
    yield
    api_clients._cache.clear()
    deps._USER_CACHE.clear()


def _request(headers, cookies="", path_params=None, settings=None, sso=None):
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    if cookies:
        raw.append((b"cookie", cookies.encode()))
    services = SimpleNamespace(
        settings=settings or Settings(), db=_REQUEST_DB[0]
    )
    app = SimpleNamespace(state=SimpleNamespace(services=services, sso=sso))
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/x",
            "headers": raw,
            "app": app,
            "path_params": path_params or {},
            "query_string": b"",
        }
    )
    return request


_REQUEST_DB: list[Any] = [None]


def _authenticate(db, headers, **kw):
    _REQUEST_DB[0] = db
    request = _request(headers, **kw)
    user = asyncio.run(deps.current_user(request))
    return request, user


def test_key_caller_acts_as_the_user_it_names():
    db = _Db([_client()], [_user()])
    request, user = _authenticate(
        db, {"X-Api-Key": KEY, "X-User-Id": USER.upper()}
    )
    assert user.id == USER  # lowercased before the lookup
    assert deps.caller_of(request) == api_clients.Caller(
        "c-1", "partner-agent", "partner"
    )


@pytest.mark.parametrize("status", ["pending", "revoked"])
def test_keys_not_active_are_refused(status):
    db = _Db([_client(status)], [_user()])
    with pytest.raises(ApiError) as err:
        _authenticate(db, {"X-Api-Key": KEY, "X-User-Id": USER})
    assert err.value.status == 401


def test_unknown_key_is_refused():
    with pytest.raises(ApiError) as err:
        _authenticate(_Db(), {"X-Api-Key": "pas_dev_x", "X-User-Id": USER})
    assert err.value.status == 401


@pytest.mark.parametrize("user_id", [None, "Bad Id", "-x", "a" * 65])
def test_user_header_is_required_and_checked(user_id):
    headers = {"X-Api-Key": KEY}
    if user_id:
        headers["X-User-Id"] = user_id
    with pytest.raises(ApiError) as err:
        _authenticate(_Db([_client()], [_user()]), headers)
    assert (err.value.status, err.value.code) == (400, "INVALID_IDENTITY")


@pytest.mark.parametrize("users", [[], [_user(active=False)]])
def test_unknown_or_inactive_users_are_forbidden(users):
    with pytest.raises(HTTPException) as err:
        _authenticate(
            _Db([_client()], users), {"X-Api-Key": KEY, "X-User-Id": USER}
        )
    assert err.value.status_code == 403


def test_employee_id_names_the_same_user():
    _, user = _authenticate(
        _Db([_client(tenant="pr-agentic")], [_user()]),
        {"X-Api-Key": KEY, "X-User-Id": "E1"},
    )
    assert user.id == USER


def test_outside_tenants_bring_their_own_user_ids():
    _REQUEST_DB[0] = _Db([_client(tenant="partner")], [])
    request = _request({"X-Api-Key": KEY, "X-User-Id": "Their.User-7"})
    services = request.app.state.services
    caller, user_id, user = asyncio.run(
        deps.key_identity(request, services, any_user_outside=True)
    )
    assert (caller.tenant, user_id, user) == ("partner", "their.user-7", None)
    # our own APIs still need one of our users
    with pytest.raises(HTTPException) as err:
        asyncio.run(deps.key_identity(request, services))
    assert err.value.status_code == 403


def test_outside_tenants_cannot_act_for_one_we_deactivated():
    # the same employee id is the same person in every tenant
    gone = User(
        id="e1", employee_id="E1", name="n", role="user", is_active=False
    )
    _REQUEST_DB[0] = _Db([_client(tenant="partner")], [gone])
    request = _request({"X-Api-Key": KEY, "X-User-Id": "E1"})
    services = request.app.state.services
    with pytest.raises(HTTPException) as err:
        asyncio.run(
            deps.key_identity(request, services, any_user_outside=True)
        )
    assert err.value.status_code == 403


@pytest.mark.parametrize(
    ("user_id", "ok"),
    [("E12345", True), ("svc-report", True), ("their.user-7", False)],
)
def test_outside_users_are_employee_ids_when_a_pattern_is_set(user_id, ok):
    _REQUEST_DB[0] = _Db([_client(tenant="partner")], [])
    settings = Settings(employee_id_pattern=r"e[0-9]{5}")
    request = _request(
        {"X-Api-Key": KEY, "X-User-Id": user_id}, settings=settings
    )
    services = request.app.state.services
    run = deps.key_identity(request, services, any_user_outside=True)
    if ok:
        assert asyncio.run(run)[1] == user_id.lower()
        return
    with pytest.raises(ApiError) as err:
        asyncio.run(run)
    assert (err.value.status, err.value.code) == (400, "INVALID_IDENTITY")


def test_our_user_id_is_the_lowercased_employee_id():
    from api_service.users import user_id_of

    assert user_id_of(" E12345 ") == "e12345"
    for bad in ["", "-e1", "e" * 37, "김철수"]:
        with pytest.raises(HTTPException):
            user_id_of(bad)


def test_our_tenant_needs_our_users_on_gateways_too():
    _REQUEST_DB[0] = _Db([_client(tenant="dtest-agent-service")], [])
    request = _request({"X-Api-Key": KEY, "X-User-Id": "someone"})
    with pytest.raises(HTTPException) as err:
        asyncio.run(
            deps.key_identity(
                request, request.app.state.services, any_user_outside=True
            )
        )
    assert err.value.status_code == 403


def test_project_header_must_match_the_path():
    headers = {"X-Api-Key": KEY, "X-User-Id": USER, "X-Project-Id": "p-2"}
    with pytest.raises(ApiError) as err:
        _authenticate(
            _Db([_client()], [_user()]),
            headers,
            path_params={"project_id": "p-1"},
        )
    assert err.value.status == 400
    headers["X-Project-Id"] = "p-1"
    _authenticate(
        _Db([_client()], [_user()]), headers, path_params={"project_id": "p-1"}
    )


def test_session_header_needs_a_project():
    headers = {"X-Api-Key": KEY, "X-User-Id": USER, "X-Session-Id": "s"}
    with pytest.raises(ApiError):
        _authenticate(_Db([_client()], [_user()]), headers)


def test_without_key_or_cookie_login_is_required():
    with pytest.raises(HTTPException) as err:
        _authenticate(_Db(), {"X-User-Id": USER})
    assert err.value.status_code == 401


def test_the_cookie_decides_when_both_are_sent():
    class Sso:
        async def authenticate(self, request):
            return SimpleNamespace(user_id=USER)

    request, user = _authenticate(
        _Db(users=[_user()]),
        {"X-Api-Key": "pas_dev_unknown", "X-User-Id": "someone-else"},
        cookies="agentic_session=sid",
        sso=Sso(),
    )
    assert user.id == USER and deps.caller_of(request) is None


def test_admin_apis_refuse_key_callers():
    request, user = _authenticate(
        _Db([_client()], [_user(role="admin")]),
        {"X-Api-Key": KEY, "X-User-Id": USER},
    )
    with pytest.raises(HTTPException) as err:
        asyncio.run(deps.admin_user(request, user))
    assert err.value.status_code == 403


def test_sso_only_apis_refuse_key_callers():
    _REQUEST_DB[0] = _Db([_client()], [_user(role="admin")])
    request = _request({"X-Api-Key": KEY, "X-User-Id": USER})
    with pytest.raises(HTTPException) as err:
        asyncio.run(deps.sso_user(request))
    assert err.value.status_code == 403
    with pytest.raises(HTTPException) as err:
        asyncio.run(deps.sso_user(_request({})))
    assert err.value.status_code == 401


def test_a_key_alone_reads_what_is_no_ones():
    _REQUEST_DB[0] = _Db([_client()], [_user()])
    request = _request({"X-Api-Key": KEY})
    assert asyncio.run(deps.user_or_service(request)) is None
    assert deps.caller_of(request) is not None
    named = _request({"X-Api-Key": KEY, "X-User-Id": USER})
    user = asyncio.run(deps.user_or_service(named))
    assert user is not None and user.id == USER


def test_a_revoked_key_is_forgotten_here_at_once():
    client = _client()
    db = _Db([client], [_user()])
    _authenticate(db, {"X-Api-Key": KEY, "X-User-Id": USER})
    client.status = "revoked"
    api_clients.forget(client.key_sha256)
    with pytest.raises(ApiError):
        _authenticate(db, {"X-Api-Key": KEY, "X-User-Id": USER})


def test_keys_are_random_and_only_hashed():
    one, two = api_clients.new_key("prd"), api_clients.new_key("dev")
    assert one.startswith("pas_live_") and two.startswith("pas_dev_")
    assert len(one) > 40 and one != api_clients.new_key("prd")
    assert len(api_clients.digest(one)) == 64


# --- pr-batch gateway ------------------------------------------------------


def _gateway(method, path, headers, caller=None, member=True):
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    request = Request(
        {"type": "http", "method": method, "path": "/", "headers": raw}
    )
    request.state.api_client = caller
    services = SimpleNamespace(settings=Settings(executor_tenant_id="ours"))

    async def project_for(services, user, project_id, write=False):
        if not member:
            raise HTTPException(404, "Project not found.")

    batch.project_for = project_for
    user = SimpleNamespace(id=USER)
    return asyncio.run(
        batch.gateway_identity(
            cast(Any, services), request, path, USER, cast(Any, user)
        )
    )


def test_browser_registers_batches_in_our_tenant(monkeypatch):
    monkeypatch.setattr(batch, "project_for", batch.project_for)
    who = _gateway("POST", "batches", {"X-Project-Id": "p-1"})
    assert who.headers() == {
        "X-User-Id": USER,
        "X-Project-Id": "p-1",
        "X-Tenant-Id": "ours",
    }
    with pytest.raises(HTTPException):
        _gateway("POST", "batches", {"X-Project-Id": "p-1"}, member=False)


def test_key_caller_registers_in_its_tenant(monkeypatch):
    monkeypatch.setattr(batch, "project_for", batch.project_for)
    caller = api_clients.Caller("c", "partner-agent", "partner")
    who = _gateway(
        "POST", "batches", {"X-Project-Id": "theirs"}, caller, member=False
    )
    assert who.tenant == "partner" and who.project_id == "theirs"


def test_every_call_names_the_tenant_registration_the_project(monkeypatch):
    # pr-batch finds scripts and batches by (tenant, user): a call without
    # the tenant would look in the key's default one (or "dev" in header
    # mode) and answer 404
    monkeypatch.setattr(batch, "project_for", batch.project_for)
    who = _gateway("PATCH", "batches/b-1", {"X-Project-Id": "p-1"})
    assert who.headers() == {"X-User-Id": USER, "X-Tenant-Id": "ours"}
    caller = api_clients.Caller("c", "partner-agent", "partner")
    for method, path in [("POST", "scripts"), ("GET", "batches/b-1")]:
        who = _gateway(method, path, {}, caller, member=False)
        assert who.headers() == {"X-User-Id": USER, "X-Tenant-Id": "partner"}
    assert _gateway("GET", "runtimes", {}).headers() == {}  # key only


def test_disable_by_owner_call(monkeypatch):
    sent: list[httpx.Request] = []

    def handle(request):
        sent.append(request)
        return httpx.Response(200, json={"disabled": 2})

    real = httpx.AsyncClient

    def client(**kw):
        return real(transport=httpx.MockTransport(handle), **kw)

    monkeypatch.setattr(batch_admin.httpx, "AsyncClient", client)
    settings = Settings(batch_api_key="bat_test_k")
    assert asyncio.run(batch_admin.disable_batches_of(settings, USER)) == 2
    assert sent[0].url.path == "/api/v1/batches:disable-by-owner"
    assert sent[0].headers["x-api-key"] == "bat_test_k"
    assert "x-user-id" not in sent[0].headers
    # every tenant of our key, not ours alone
    assert "x-tenant-id" not in sent[0].headers
    assert json.loads(sent[0].content) == {
        "owner_id": USER,
        "reason": "USER_DEACTIVATED",
    }


def test_a_failed_disable_stays_pending(monkeypatch):
    async def down(settings, owner_id):
        raise httpx.ConnectError("pr-batch down")

    monkeypatch.setattr(batch_admin, "disable_batches_of", down)
    services = cast(Any, SimpleNamespace(settings=Settings(), db=None))
    assert asyncio.run(batch_admin.tell_batch(services, USER)) is False


def test_disable_by_tenant_call(monkeypatch):
    sent: list[httpx.Request] = []
    real = httpx.AsyncClient

    def client(**kw):
        def handle(request):
            sent.append(request)
            return httpx.Response(200, json={"disabled": 3})

        return real(transport=httpx.MockTransport(handle), **kw)

    monkeypatch.setattr(batch_admin.httpx, "AsyncClient", client)
    settings = Settings(batch_api_key="bat_test_k")
    disabled = asyncio.run(
        batch_admin.disable_batches_of_tenant(settings, "partner")
    )
    assert disabled == 3
    assert sent[0].url.path == "/api/v1/batches:disable-by-tenant"
    assert sent[0].headers["x-api-key"] == "bat_test_k"
    assert sent[0].headers["x-tenant-id"] == "partner"
    assert "x-user-id" not in sent[0].headers
    assert json.loads(sent[0].content) == {"reason": "TENANT_REVOKED"}


def test_a_failed_tenant_disable_stays_pending(monkeypatch):
    async def down(settings, tenant):
        raise httpx.ConnectError("pr-batch down")

    monkeypatch.setattr(batch_admin, "disable_batches_of_tenant", down)
    services = cast(Any, SimpleNamespace(settings=Settings(), db=None))
    told = asyncio.run(batch_admin.tell_batch_tenant(services, "partner"))
    assert told is False


# --- events ------------------------------------------------------------------


class _Redis:
    def __init__(self):
        self.acked = []

    async def xack(self, stream, group, message_id):
        self.acked.append(message_id)


class _Timeline:
    def __init__(self, items):
        self.items = items

    async def event(self, execution_id, sequence):
        return next(
            (i for i in self.items if i["event_sequence"] == sequence), None
        )


def _consume(timeline, fields, monkeypatch):
    delivered = []

    async def deliver(db, event):
        delivered.append(event)
        return None

    monkeypatch.setattr(executor_events, "deliver", deliver)

    async def completed(execution_id, payload):
        delivered.append(("completed", payload))

    redis = _Redis()
    consumer = executor_events.ExecutorEventConsumer(
        cast(Any, None),
        cast(Any, redis),
        "s",
        "g",
        "c",
        on_wake=None,
        on_progress=None,
        on_completed=completed,
        executor=cast(Any, timeline),
    )
    asyncio.run(consumer._handle("m1", fields))
    return delivered, redis.acked


def _fields(payload):
    return {
        "event_id": "e-1",
        "execution_id": "x-1",
        "event_type": "execution.completed",
        "event_sequence": "9",
        "payload": json.dumps(payload),
    }


def test_wake_events_are_taken_from_the_executor(monkeypatch):
    timeline = _Timeline(
        [
            {
                "event_id": "e-1",
                "event_type": "execution.completed",
                "event_sequence": 9,
                "payload": {"status": "FAILED"},
            }
        ]
    )
    delivered, acked = _consume(
        timeline, _fields({"status": "SUCCEEDED", "forged": True}), monkeypatch
    )
    assert delivered[0]["payload"] == {"status": "FAILED"}
    assert delivered[1] == ("completed", {"status": "FAILED"})
    assert acked == ["m1"]


def test_events_the_executor_does_not_know_are_dropped(monkeypatch):
    delivered, acked = _consume(
        _Timeline([]), _fields({"status": "SUCCEEDED"}), monkeypatch
    )
    assert delivered == [] and acked == ["m1"]


# --- logs --------------------------------------------------------------------


def test_keys_are_masked_in_logs():
    record = logging.LogRecord(
        "x",
        logging.INFO,
        "f",
        1,
        "sent %s and %s",
        ("exe_live_abc", KEY),
        None,
    )
    SecretFilter().filter(record)
    assert record.getMessage() == "sent *** and ***"
