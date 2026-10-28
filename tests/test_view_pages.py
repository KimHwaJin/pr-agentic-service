import asyncio
import json
import tempfile
from functools import cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from src.dtest.api_service.routers import batch
from src.dtest.api_service.routers.artifacts import render_view
from src.dtest.core.config import Settings

SCRIPT = UUID("58623b2f-216e-4edc-b251-b5e8975c04f3")
VERSION = UUID("6ee4a862-3ddd-49dc-aceb-fac516450cea")


def _cells(html: str) -> str:
    return html.split("const CELLS = ", 1)[1].split(";", 1)[0]


def test_artifact_page_is_unchanged_without_cells():
    html = render_view(
        title="리포트 <b>",
        badge="NOTEBOOK",
        content="/api/v1/artifacts/a-1/content",
        kind="notebook",
    )
    assert "__" not in html.split("<style>", 1)[0]  # every slot filled
    assert html.count("/api/v1/artifacts/a-1/content") == 2
    assert "리포트 &lt;b&gt;" in html
    assert _cells(html) == "null"  # no Step / 건너뜀 marks


def test_cells_cannot_close_the_script_tag():
    html = render_view(
        title="t",
        badge="b",
        content="/c",
        kind="notebook",
        cells=[{"index": 0, "executed": False, "x": "</script>"}],
    )
    assert "</script>" not in _cells(html)
    assert json.loads(_cells(html))[0]["x"] == "</script>"


class _PrBatch:
    def __init__(self, status=200):
        self.status, self.calls = status, []

    async def get(self, url, headers):
        self.calls.append((url, headers["Authorization"][:7]))
        if url.endswith(str(VERSION)):
            body = {
                "version_number": 1,
                "cell_list": [
                    {"index": 0, "type": "markdown", "executed": False},
                    {
                        "index": 1,
                        "type": "code",
                        "executed": True,
                        "sequence": 0,
                    },
                ],
            }
        else:
            body = {"name": "yield-daily-test"}
        return httpx.Response(self.status, json=body)


@cache
def _key_pair() -> tuple[Path, rsa.RSAPublicKey]:
    """A throwaway RS256 pair like pr-batch's `make auth-keys`."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = Path(tempfile.mkdtemp()) / "auth_private.pem"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return path, key.public_key()


def _key_file() -> Path:
    return _key_pair()[0]


def test_batch_token_is_what_pr_batch_verifies():
    services = SimpleNamespace(
        settings=Settings(batch_jwt_private_key_file=str(_key_file()))
    )
    user = SimpleNamespace(id="0c8a2f86-5d0e-4e55-9a3c-6f2f0f6a1b11")
    token = batch._batch_token(services, user)
    assert jwt.get_unverified_header(token)["alg"] == "RS256"
    claims = jwt.decode(
        token,
        _key_pair()[1],
        algorithms=["RS256"],
        audience="batch-service",
        issuer="batch-client",
        options={"require": ["exp", "iat", "sub", "iss", "aud"]},
    )
    assert claims["sub"] == user.id
    assert claims["scope"] == "batch:manage"
    assert 0 < claims["exp"] - claims["iat"] <= 300


def test_batch_token_without_a_key_is_not_configured():
    services = SimpleNamespace(
        settings=Settings(batch_jwt_private_key_file="")
    )
    with pytest.raises(HTTPException) as err:
        batch._batch_token(services, SimpleNamespace(id="u"))
    assert err.value.status_code == 503


def _view(monkeypatch, client):
    monkeypatch.setattr(batch, "_client", lambda services: client)
    services = SimpleNamespace(
        settings=Settings(batch_jwt_private_key_file=str(_key_file()))
    )
    user = SimpleNamespace(id="0c8a2f86-5d0e-4e55-9a3c-6f2f0f6a1b11")
    return asyncio.run(
        batch.batch_script_view(
            SCRIPT, VERSION, cast(Any, services), cast(Any, user)
        )
    )


def test_batch_script_page_reads_through_the_gateway(monkeypatch):
    client = _PrBatch()
    html = _view(monkeypatch, client)
    content = f"/api/v1/batch/scripts/{SCRIPT}/versions/{VERSION}/content"
    assert html.count(content) == 2
    assert "yield-daily-test · v1" in html
    assert json.loads(_cells(html)) == [
        {"index": 0, "executed": False, "sequence": None},
        {"index": 1, "executed": True, "sequence": 0},
    ]
    assert all(auth == "Bearer " for _, auth in client.calls)


def test_batch_script_page_hides_scripts_of_others(monkeypatch):
    with pytest.raises(HTTPException) as missing:
        _view(monkeypatch, _PrBatch(status=404))
    assert missing.value.status_code == 404
