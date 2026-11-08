"""The login routes answer 429 past the per-IP call limit."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from api_service import rate_limit


def _request(app, ip="10.0.0.1", forwarded=""):
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request(
        {
            "type": "http",
            "app": app,
            "headers": headers,
            "client": (ip, 1234),
        }
    )


def _app(limit):
    app = FastAPI()
    settings = SimpleNamespace(sso_rate_limit_per_minute=limit)
    app.state.services = SimpleNamespace(settings=settings)
    return app


@pytest.fixture(autouse=True)
def _fresh():
    rate_limit._calls.clear()
    yield
    rate_limit._calls.clear()


async def test_over_limit_is_429_with_retry_after():
    app = _app(3)
    for _ in range(3):
        await rate_limit.sso_rate_limit(_request(app))
    with pytest.raises(HTTPException) as caught:
        await rate_limit.sso_rate_limit(_request(app))
    assert caught.value.status_code == 429
    assert int(caught.value.headers["Retry-After"]) >= 1
    # another client is not affected
    await rate_limit.sso_rate_limit(_request(app, ip="10.0.0.2"))


async def test_forwarded_client_is_counted():
    app = _app(1)
    await rate_limit.sso_rate_limit(
        _request(app, forwarded="1.1.1.1, 10.0.0.9")
    )
    await rate_limit.sso_rate_limit(
        _request(app, forwarded="2.2.2.2, 10.0.0.9")
    )
    with pytest.raises(HTTPException):
        await rate_limit.sso_rate_limit(_request(app, forwarded="1.1.1.1"))


async def test_zero_turns_it_off():
    app = _app(0)
    for _ in range(100):
        await rate_limit.sso_rate_limit(_request(app))
