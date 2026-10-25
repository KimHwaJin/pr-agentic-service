import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx

log = logging.getLogger(__name__)

AGENT_ACTOR = {"type": "AGENT", "id": "pr-agentic-service"}


def trigger_type(execution: dict[str, Any]) -> str | None:
    """INTERACTIVE | BATCH of an execution or an event's ``execution``."""
    return (execution.get("trigger") or {}).get("type")


class ExecutorError(Exception):
    def __init__(self, status: int, body: Any):
        super().__init__(f"executor error {status}: {body}")
        self.status, self.body = status, body

    @property
    def code(self) -> str | None:
        """The executor's error code (``{"error": {"code": ...}}``)."""
        error = self.body.get("error") if isinstance(self.body, dict) else None
        return error.get("code") if isinstance(error, dict) else None


class ExecutorClient:
    """Executor REST v1.

    Every mutation carries a caller-derived idempotency key so a replayed
    call (pod crash, graph replay) returns the original receipt.
    """

    def __init__(
        self, base_url: str, timeout: float, tenant_id: str | None = None
    ):
        self.http = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/api/v1", timeout=timeout
        )
        # decides the event stream of every execution submitted here
        self.tenant_id = tenant_id

    async def close(self) -> None:
        await self.http.aclose()

    async def _call(self, method: str, url: str, **kwargs: Any) -> Any:
        response = await self.http.request(method, url, **kwargs)
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = response.text
            log.warning(
                "executor_error method=%s url=%s status=%s body=%s",
                method,
                url,
                response.status_code,
                body,
            )
            raise ExecutorError(response.status_code, body)
        return response.json() if response.content else None

    async def submit(
        self,
        *,
        idempotency_key: str,
        context: dict[str, str],
        steps: list[dict[str, Any]],
        profile: str,
        wait_seconds: int | None,
        trigger: str = "INTERACTIVE",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        lifecycle: dict[str, Any] = {
            "operation_mode": "MULTI" if wait_seconds else "SINGLE"
        }
        if wait_seconds:
            lifecycle["operation_wait_timeout_seconds"] = wait_seconds
        body = {
            "idempotency_key": idempotency_key,
            **({"tenant_id": self.tenant_id} if self.tenant_id else {}),
            "lifecycle": lifecycle,
            "trigger": {"type": trigger, "actor": AGENT_ACTOR},
            "runtime": {"type": "JUPYTER", "profile": profile},
            "context": context,
            "operation": {"spec": {"schema_version": "1.0", "steps": steps}},
            "metadata": metadata or {},
        }
        return await self._call("POST", "/executions", json=body)

    async def append_operation(
        self,
        execution_id: str,
        *,
        idempotency_key: str,
        expected_version: int,
        steps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        body = {
            "idempotency_key": idempotency_key,
            "expected_version": expected_version,
            "spec": {"schema_version": "1.0", "steps": steps},
            "actor": AGENT_ACTOR,
        }
        return await self._call(
            "POST", f"/executions/{execution_id}/operations", json=body
        )

    async def finalize(
        self, execution_id: str, *, idempotency_key: str, expected_version: int
    ) -> dict[str, Any]:
        body = {
            "idempotency_key": idempotency_key,
            "expected_version": expected_version,
            "actor": AGENT_ACTOR,
        }
        return await self._call(
            "POST", f"/executions/{execution_id}/finalize", json=body
        )

    async def cancel(
        self, execution_id: str, *, idempotency_key: str, reason: str
    ) -> dict[str, Any]:
        body = {
            "idempotency_key": idempotency_key,
            "reason": reason,
            "actor": AGENT_ACTOR,
        }
        return await self._call(
            "POST", f"/executions/{execution_id}/cancel", json=body
        )

    async def get(self, execution_id: str) -> dict[str, Any]:
        return await self._call("GET", f"/executions/{execution_id}")

    async def events(self, execution_id: str) -> list[dict[str, Any]]:
        """The execution's durable event timeline, oldest first."""
        items: list[dict[str, Any]] = []
        cursor = None
        while True:
            page = await self._call(
                "GET",
                f"/executions/{execution_id}/events",
                params={
                    "limit": 200,
                    **({"cursor": cursor} if cursor else {}),
                },
            )
            items += page["items"]
            cursor = page.get("next_cursor")
            if not cursor:
                return items

    async def executions(
        self, created_after: datetime, **filters: str
    ) -> list[dict[str, Any]]:
        """Executions created after ``created_after``, newest first.

        ``filters`` are the list's query parameters (``tenant_id``,
        ``trigger_type``, ``status``, ...). The list has no time filter, so
        pages are read until they pass ``created_after``.
        """
        items: list[dict[str, Any]] = []
        cursor = None
        while True:
            page = await self._call(
                "GET",
                "/executions",
                params={
                    **filters,
                    "limit": 200,
                    **({"cursor": cursor} if cursor else {}),
                },
            )
            for item in page["items"]:
                if datetime.fromisoformat(item["created_at"]) < created_after:
                    return items
                items.append(item)
            cursor = page.get("next_cursor")
            if not cursor:
                return items

    async def result(self, execution_id: str) -> dict[str, Any]:
        return await self._call("GET", f"/executions/{execution_id}/result")

    async def notebook(self, execution_id: str) -> dict[str, Any] | None:
        """The execution's notebook artifact in full.

        The execution's artifact list leaves out ``storage.relative_path``
        (the JupyterLab link needs it), so the notebook is read on its own.
        """
        page = await self._call(
            "GET",
            f"/executions/{execution_id}/artifacts",
            params={"limit": 200},
        )
        found = next(
            (a for a in page["items"] if a["type"] == "NOTEBOOK"), None
        )
        return await self.artifact(found["artifact_id"]) if found else None

    async def artifact(self, artifact_id: str) -> dict[str, Any]:
        return await self._call("GET", f"/artifacts/{artifact_id}")

    async def create_report(
        self,
        execution_id: str,
        *,
        idempotency_key: str,
        markdown: str,
        name: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        body = {
            "idempotency_key": idempotency_key,
            "type": "REPORT",
            "source": {"type": "INLINE", "content": markdown},
            "name": name,
            "media_type": "text/markdown",
            "append_to_notebook": True,
            "metadata": metadata,
            "actor": AGENT_ACTOR,
        }
        return await self._call(
            "POST", f"/executions/{execution_id}/artifacts", json=body
        )

    async def stream_artifact(
        self, artifact_id: str
    ) -> tuple[httpx.Response, AsyncIterator[bytes]]:
        request = self.http.build_request(
            "GET", f"/artifacts/{artifact_id}/content"
        )
        response = await self.http.send(request, stream=True)
        if response.status_code >= 400:
            await response.aread()
            raise ExecutorError(response.status_code, response.text)
        return response, response.aiter_bytes()
