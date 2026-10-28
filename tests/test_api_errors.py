import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.dtest.api_service import errors
from src.dtest.api_service.schemas.projects import ProjectUpdate


def test_unreachable_upstream_is_a_bad_gateway():
    app = FastAPI()
    errors.install(app)

    @app.get("/api/v1/x")
    async def down():
        raise httpx.ConnectError("refused")

    response = TestClient(app).get("/api/v1/x")
    assert response.status_code == 502
    assert response.json()["code"] == "bad_gateway"


def test_other_apis_on_the_app_keep_their_error_handlers():
    # the gaia template's routes share the app
    app = FastAPI()

    async def theirs(request, exc):
        return JSONResponse(
            {"theirs": exc.detail}, status_code=exc.status_code
        )

    app.add_exception_handler(HTTPException, theirs)
    errors.install(app)

    @app.get("/api/v1/mine")
    async def mine():
        raise HTTPException(404, "gone")

    @app.get("/workflows")
    async def gaia():
        raise HTTPException(404, "gone")

    @app.post("/api/common/body")
    async def body(n: int):
        return n

    client = TestClient(app)
    assert client.get("/api/v1/mine").json()["code"] == "not_found"
    assert client.get("/workflows").json() == {"theirs": "gone"}
    invalid = client.post("/api/common/body")
    assert invalid.status_code == 422 and "code" not in invalid.json()


def test_patch_null_clears_only_nullable_fields():
    body = ProjectUpdate.model_validate(
        {"name": None, "description": "d", "code_level": None}
    )
    assert body.changes(nullable={"code_level"}) == {
        "description": "d",
        "code_level": None,
    }
