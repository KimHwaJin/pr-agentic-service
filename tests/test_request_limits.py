"""Oversized request bodies are refused before they are read."""

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.dtest.api_service.app import mount_api
from src.dtest.core.config import Settings


def test_a_body_over_the_limit_is_refused():
    app = FastAPI()
    mount_api(app, Settings(request_max_bytes=1000))
    client = TestClient(app)
    response = client.post(
        "/api/v1/sessions/s/runs",
        content=b"x" * 1001,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["code"] == "too_large"


def test_a_chunked_body_over_the_limit_is_stopped():
    app = FastAPI()
    mount_api(app, Settings(request_max_bytes=1000))

    @app.post("/echo")
    async def echo(request: Request):
        return {"size": len(await request.body())}

    client = TestClient(app)

    def chunks(n):
        for _ in range(n):
            yield b"x" * 400

    big = client.post("/echo", content=chunks(5))  # no Content-Length
    assert big.status_code == 413
    small = client.post("/echo", content=chunks(2))
    assert small.json() == {"size": 800}
