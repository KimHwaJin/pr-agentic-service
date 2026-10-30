"""Step results from the executor notebook API (test environments only).

A Step's result_ref names a manifest on the executor's result volume::

    executions/<execution>/operations/<op>/steps/<step>/attempts/...

Without the volume the execution and step ids are taken from that path,
and the step's notebook cell is read instead. The executor writes one
code cell per step in sequence order (reports are appended after them),
so a step's cell index is its sequence unless the cell metadata says
otherwise.

The callers are synchronous, so the API is called with a blocking client;
these calls are short and this mode is for tests only.
"""

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from core.executor.storage import TEXT_TYPES, SharedStorage
from core.service_headers import Identity, with_key

_RESULT_PATH = re.compile(
    r"executions/(?P<execution>[^/]+)/operations/[^/]+/steps/(?P<step>[^/]+)/"
)


def step_of(result_ref: dict[str, Any] | None) -> tuple[str, str] | None:
    """(execution id, step id) of a result_ref, or None."""
    match = _RESULT_PATH.match((result_ref or {}).get("relative_path", ""))
    return (match["execution"], match["step"]) if match else None


def _text(value: Any) -> str:
    """nbformat text: a string or a list of lines; JSON data as JSON."""
    if isinstance(value, list):
        return "".join(map(str, value))
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def cell_outputs(cell: dict[str, Any], max_chars: int) -> dict[str, Any]:
    """The read_step_outputs view of one notebook cell."""
    texts: list[str] = []
    errors: list[str] = []
    budget, truncated = max_chars, False
    for output in cell.get("outputs") or []:
        kind = output.get("output_type")
        if kind == "error":
            errors.append(
                f"{output.get('ename', '')}: {output.get('evalue', '')}"
            )
            continue
        if kind == "stream":
            text = _text(output.get("text", ""))
        else:  # execute_result, display_data
            data = output.get("data") or {}
            if any(k.startswith("image/") for k in data):
                # a figure's text/plain twin ("<Figure ...>") adds nothing
                continue
            media = next((m for m in TEXT_TYPES if m in data), None)
            if media is None:
                continue
            text = _text(data[media])
        if truncated:
            continue
        truncated = len(text) > budget
        texts.append(text[:budget])
        budget -= len(texts[-1])
    return {
        "available": True,
        "complete": True,
        "text": "\n".join(texts),
        "truncated": truncated,
        "images": [],  # image files live on the result volume
        "error": "\n".join(errors) or None,
    }


class NotebookResultStorage(SharedStorage):
    """SharedStorage reading results through the executor notebook API.

    The reads are system reads of our tenant, with the key and tenant of
    ``ExecutorClient``: without them an API-key executor answers 401 and a
    header-mode one looks in its default tenant (404).
    """

    def __init__(
        self,
        *args: Any,
        base_url: str,
        timeout: float,
        api_key: str = "",
        tenant: str = "",
        transport: httpx.BaseTransport | None = None,  # tests
    ):
        super().__init__(*args)
        self.api_url = base_url.rstrip("/") + "/api/v1"
        self.timeout = timeout
        self.headers = with_key(api_key, Identity(tenant=tenant or None))
        self.transport = transport

    def source_file(self, relative: str) -> Path:
        """A short flat name for the file sent as ``sources/<relative>``.

        The executor-side path nests five ids (~190 characters), which a
        Windows checkout pushes past MAX_PATH (260): the folders get made
        but the file write fails. Nothing reads these copies by path but
        this service, so they are kept as ``sources/<hash>-<file name>``.
        """
        digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16]
        name = PurePosixPath(relative).name or "source.py"
        return self.sources_root.resolve() / f"{digest}-{name}"

    def read_step_outputs(
        self, result_ref: dict[str, Any] | None, max_chars: int = 12000
    ) -> dict[str, Any]:
        if not result_ref:
            return {"available": False}
        try:
            cell = self._cell(result_ref)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            return {
                "available": False,
                "error": f"노트북 셀을 읽지 못했습니다: {type(exc).__name__}",
            }
        return cell_outputs(cell, max_chars)

    def step_source(
        self, result_ref: dict[str, Any], limit: int = 2000
    ) -> str:
        try:
            return _text(self._cell(result_ref).get("source", ""))[:limit]
        except (httpx.HTTPError, KeyError, ValueError):
            return ""

    def _cell(self, result_ref: dict[str, Any]) -> dict[str, Any]:
        ids = step_of(result_ref)
        if ids is None:
            raise ValueError("result_ref names no execution step")
        execution_id, step_id = ids
        base = f"/executions/{execution_id}"
        with httpx.Client(
            base_url=self.api_url,
            timeout=self.timeout,
            headers=self.headers,
            transport=self.transport,
        ) as http:
            step = _get(http, f"{base}/steps/{step_id}")
            sequence = step["sequence"]
            cell = _get(http, f"{base}/notebook/cells/{sequence}")["cell"]
            if _belongs(cell, step_id, sequence) is False:
                cell = _find(http, base, step_id, sequence) or cell
        return cell


def _get(http: httpx.Client, url: str, **params: Any) -> dict[str, Any]:
    response = http.get(url, params=params)
    response.raise_for_status()
    return response.json()


def _belongs(cell: dict[str, Any], step_id: str, sequence: int) -> bool | None:
    """Whether the cell metadata names this step; None if it names none."""
    meta = cell.get("metadata") or {}
    meta = meta.get("executor", meta)
    if "step_id" in meta:
        return str(meta["step_id"]) == step_id
    if "sequence" in meta:
        return meta["sequence"] == sequence
    return None


def _find(
    http: httpx.Client, base: str, step_id: str, sequence: int
) -> dict[str, Any] | None:
    """The cell whose metadata names the step (full read of that cell)."""
    start = 0
    while True:
        page = _get(
            http,
            f"{base}/notebook",
            view="SUMMARY",
            start_index=start,
            limit=200,
        )
        for cell in page["cells"]:
            if _belongs(cell, step_id, sequence):
                return _get(http, f"{base}/notebook/cells/{cell['index']}")[
                    "cell"
                ]
        if not page["page"]["has_more"]:
            return None
        start += len(page["cells"])
