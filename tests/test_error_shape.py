"""Every error has {"error": {code, message, details[], context?}}."""

import json

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from src.dtest.api_service import errors
from src.dtest.api_service.errors import ApiError, detail
from src.dtest.api_service.routers.batch import _batch_error


class Body(BaseModel):
    name: str = Field(max_length=3)


def _client() -> TestClient:
    app = FastAPI()
    errors.install(app)

    @app.post("/api/v1/v")
    async def v(body: Body):
        return {}

    @app.get("/api/v1/h")
    async def h():
        raise HTTPException(409, "Cancel the running turns first.")

    @app.get("/api/v1/a")
    async def a():
        raise ApiError(
            422,
            "execution_step_limit_exceeded",
            "Too many steps.",
            [
                detail(
                    ["body", "spec", "steps"],
                    "execution_step_limit_exceeded",
                    "Too many steps.",
                    {"limit": 1000, "existing": 990, "requested": 20},
                )
            ],
            run={"id": "r1"},
        )

    return TestClient(app)


def test_validation_error_lists_location_type_and_context():
    error = _client().post("/api/v1/v", json={"name": "abcd"}).json()["error"]
    assert error["code"] == "INVALID_BODY"
    (d,) = error["details"]
    assert d["location"] == ["body", "name"]
    assert d["type"] == "string_too_long"
    assert d["context"] == {"max_length": 3}
    assert "abcd" not in str(error)  # the value is not echoed
    assert "context" not in error


def test_plain_http_error_gets_a_code_from_its_status():
    assert _client().get("/api/v1/h").json() == {
        "error": {
            "code": "CONFLICT",
            "message": "Cancel the running turns first.",
            "details": [],
        }
    }


def test_api_error_keeps_details_and_context():
    error = _client().get("/api/v1/a").json()["error"]
    assert error["details"][0]["context"] == {
        "limit": 1000,
        "existing": 990,
        "requested": 20,
    }
    assert error["context"] == {"run": {"id": "r1"}}


async def test_batch_errors_are_converted():
    response = await _batch_error(
        httpx.Response(
            422,
            json={
                "code": "validation_error",
                "message": "Invalid.",
                "errors": [
                    {
                        "loc": ["body", "cron"],
                        "type": "value_error",
                        "msg": "bad",
                    }
                ],
            },
        )
    )
    error = json.loads(bytes(response.body))["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"] == [
        {
            "location": ["body", "cron"],
            "type": "value_error",
            "message": "bad",
            "context": {},
        }
    ]
