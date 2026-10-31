import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_service import errors
from api_service.schemas.projects import ProjectUpdate


def test_unreachable_upstream_is_a_bad_gateway():
    app = FastAPI()
    errors.install(app)

    @app.get("/x")
    async def down():
        raise httpx.ConnectError("refused")

    response = TestClient(app).get("/x")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "bad_gateway"


def test_patch_null_clears_only_nullable_fields():
    body = ProjectUpdate.model_validate(
        {"name": None, "description": "d", "code_level": None}
    )
    assert body.changes(nullable={"code_level"}) == {
        "description": "d",
        "code_level": None,
    }
