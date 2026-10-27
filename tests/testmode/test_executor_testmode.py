"""EXECUTOR_IO_MODE=api (core/executor/testmode); remove with it."""

import asyncio
import copy
import json
from typing import Any

import httpx
import pytest

from core.config import Settings
from core.executor.storage import SharedStorage
from core.executor.testmode import (
    InlineExecutorClient,
    NotebookResultStorage,
    build,
)
from core.executor.testmode.storage import cell_outputs, step_of

EXECUTION = "11111111-1111-1111-1111-111111111111"
STEP = "22222222-2222-2222-2222-222222222222"
REF = {
    "relative_path": f"executions/{EXECUTION}/operations/op-1/steps/{STEP}"
    "/attempts/at-1/1/manifest.json"
}


def _client(tmp_path, sent: list[dict[str, Any]]):
    storage = SharedStorage(tmp_path / "svc", "svc", tmp_path / "results")
    client = InlineExecutorClient("http://executor", 5, "pr-agentic", storage)

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(202, json={"execution_id": EXECUTION})

    client.http = httpx.AsyncClient(
        base_url="http://executor/api/v1",
        transport=httpx.MockTransport(handle),
    )
    return client, storage


def _step(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "sequence": 0,
        "payload": {"type": "PYTHON_EXECUTE", "source": source},
        "lineage": {"tool_name": "t"},
    }


def test_path_steps_are_sent_inline_and_the_originals_kept(tmp_path):
    sent: list[dict[str, Any]] = []
    client, storage = _client(tmp_path, sent)
    path, _ = storage.write_source("print(1)\n", "s-1/r-1/0.py")
    steps = [_step(path), _step({"type": "INLINE", "content": "x = 1"})]
    before = copy.deepcopy(steps)

    asyncio.run(
        client.submit(
            idempotency_key="k",
            context={},
            steps=steps,
            profile="default",
            wait_seconds=600,
        )
    )
    asyncio.run(
        client.append_operation(
            EXECUTION, idempotency_key="k2", expected_version=1, steps=steps
        )
    )

    assert steps == before  # CodeSources.link still reads the PATH
    for body in sent:
        spec_steps = (body.get("operation") or body)["spec"]["steps"]
        assert spec_steps[0]["payload"]["source"] == {
            "type": "INLINE",
            "content": "print(1)\n",
        }
        assert spec_steps[0]["lineage"] == {"tool_name": "t"}
        assert spec_steps[1]["payload"]["source"]["content"] == "x = 1"


def test_only_our_own_sources_are_read(tmp_path):
    client, _ = _client(tmp_path, [])
    for path in ("other/sources/a.py", "svc/sources/../../x.py"):
        with pytest.raises(ValueError):
            client.read(path)


def test_result_ref_names_the_execution_and_step():
    assert step_of(REF) == (EXECUTION, STEP)
    assert step_of({"relative_path": "elsewhere/x.json"}) is None
    assert step_of(None) is None


def test_cell_outputs_read_like_a_manifest():
    cell = {
        "outputs": [
            {"output_type": "stream", "name": "stdout", "text": ["a\n", "b"]},
            {
                "output_type": "display_data",
                "data": {"image/png": "...", "text/plain": "<Figure>"},
            },
            {"output_type": "execute_result", "data": {"text/plain": "42"}},
            {
                "output_type": "error",
                "ename": "KeyError",
                "evalue": "'x'",
                "traceback": [],
            },
        ]
    }
    view = cell_outputs(cell, 12000)
    assert view == {
        "available": True,
        "complete": True,
        "text": "a\nb\n42",
        "truncated": False,
        "images": [],
        "error": "KeyError: 'x'",
    }
    short = cell_outputs(cell, 2)
    assert short["text"] == "a\n" and short["truncated"]


def _storage(tmp_path, cells: list[dict[str, Any]], seen: list[str]):
    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        seen.append(path)
        base = f"/executions/{EXECUTION}"
        if path == f"{base}/steps/{STEP}":
            return httpx.Response(200, json={"sequence": 1})
        if path.startswith(f"{base}/notebook/cells/"):
            index = int(path.rsplit("/", 1)[1])
            if index >= len(cells):
                return httpx.Response(404, json={})
            return httpx.Response(200, json={"cell": cells[index]})
        if path == f"{base}/notebook":
            summary = [{**c, "index": i} for i, c in enumerate(cells)]
            page = {"has_more": False}
            return httpx.Response(200, json={"cells": summary, "page": page})
        return httpx.Response(404, json={})

    return NotebookResultStorage(
        tmp_path / "svc",
        "svc",
        tmp_path / "results",
        base_url="http://executor",
        timeout=5,
        transport=httpx.MockTransport(handle),
    )


def _cell(text: str, metadata: dict[str, Any] | None = None):
    return {
        "source": f"print({text!r})",
        "metadata": metadata or {},
        "outputs": [{"output_type": "stream", "text": text}],
    }


def test_a_step_reads_the_cell_at_its_sequence(tmp_path):
    seen: list[str] = []
    storage = _storage(tmp_path, [_cell("setup"), _cell("one")], seen)
    assert storage.read_step_outputs(REF)["text"] == "one"
    assert storage.step_source(REF) == "print('one')"
    assert f"/executions/{EXECUTION}/notebook/cells/1" in seen


def test_cell_metadata_wins_over_the_sequence(tmp_path):
    cells = [
        _cell("mine", {"step_id": STEP}),
        _cell("other", {"step_id": "someone-else"}),
    ]
    storage = _storage(tmp_path, cells, [])
    assert storage.read_step_outputs(REF)["text"] == "mine"


def test_unreadable_results_are_one_steps_problem(tmp_path):
    storage = _storage(tmp_path, [], [])
    view = storage.read_step_outputs(REF)
    assert view["available"] is False and "HTTPStatusError" in view["error"]
    assert storage.read_step_outputs(None) == {"available": False}
    assert storage.step_source(REF) == ""


def test_api_mode_builds_the_testmode_pair():
    settings = Settings(executor_io_mode="api")
    client, storage = build(settings)
    assert client.storage is storage
    assert isinstance(storage, NotebookResultStorage)
    asyncio.run(client.close())
    assert Settings().executor_io_mode == "pv"
