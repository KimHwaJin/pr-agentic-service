import asyncio
import json
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException

from src.dtest.api_service.routers import batch
from src.dtest.api_service.routers.artifacts import render_view
from src.dtest.core.config import Settings

SCRIPT = UUID("58623b2f-216e-4edc-b251-b5e8975c04f3")
VERSION = UUID("6ee4a862-3ddd-49dc-aceb-fac516450cea")
USER = "0c8a2f86-5d0e-4e55-9a3c-6f2f0f6a1b11"


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
        self.calls.append((url, headers))
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


def _view(monkeypatch, client):
    monkeypatch.setattr(batch, "_client", lambda services: client)
    services = SimpleNamespace(settings=Settings(batch_api_key="bat_test_k"))
    user = SimpleNamespace(id=USER)
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
    assert all(
        headers == {"X-Api-Key": "bat_test_k", "X-User-Id": USER}
        for _, headers in client.calls
    )


def test_batch_script_page_hides_scripts_of_others(monkeypatch):
    with pytest.raises(HTTPException) as missing:
        _view(monkeypatch, _PrBatch(status=404))
    assert missing.value.status_code == 404
