import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

log = logging.getLogger(__name__)

AGENT_ACTOR = {"type": "AGENT", "id": "pr-agentic-service"}


class ExecutorError(Exception):
    def __init__(self, status: int, body: Any):
        super().__init__(f"executor error {status}: {body}")
        self.status, self.body = status, body


class ExecutorClient:
    """Executor REST v1. Every mutation carries a caller-derived idempotency key so a
    replayed call (pod crash, graph replay) returns the original receipt."""

    def __init__(self, base_url: str, timeout: float):
        self.http = httpx.AsyncClient(base_url=base_url.rstrip("/") + "/api/v1", timeout=timeout)

    async def close(self) -> None:
        await self.http.aclose()

    async def _call(self, method: str, url: str, **kwargs: Any) -> Any:
        response = await self.http.request(method, url, **kwargs)
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = response.text
            log.warning("executor_error method=%s url=%s status=%s body=%s", method, url, response.status_code, body)
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
        lifecycle: dict[str, Any] = {"operation_mode": "MULTI" if wait_seconds else "SINGLE"}
        if wait_seconds:
            lifecycle["operation_wait_timeout_seconds"] = wait_seconds
        body = {
            "idempotency_key": idempotency_key,
            "lifecycle": lifecycle,
            "trigger": {"type": trigger, "actor": AGENT_ACTOR},
            "runtime": {"type": "JUPYTER", "profile": profile},
            "context": context,
            "operation": {"spec": {"schema_version": "1.0", "steps": steps}},
            "metadata": metadata or {},
        }
        return await self._call("POST", "/executions", json=body)

    async def append_operation(
        self, execution_id: str, *, idempotency_key: str, expected_version: int, steps: list[dict[str, Any]]
    ) -> dict[str, Any]:
        body = {
            "idempotency_key": idempotency_key,
            "expected_version": expected_version,
            "spec": {"schema_version": "1.0", "steps": steps},
            "actor": AGENT_ACTOR,
        }
        return await self._call("POST", f"/executions/{execution_id}/operations", json=body)

    async def finalize(self, execution_id: str, *, idempotency_key: str, expected_version: int) -> dict[str, Any]:
        body = {"idempotency_key": idempotency_key, "expected_version": expected_version, "actor": AGENT_ACTOR}
        return await self._call("POST", f"/executions/{execution_id}/finalize", json=body)

    async def cancel(self, execution_id: str, *, idempotency_key: str, reason: str) -> dict[str, Any]:
        body = {"idempotency_key": idempotency_key, "reason": reason, "actor": AGENT_ACTOR}
        return await self._call("POST", f"/executions/{execution_id}/cancel", json=body)

    async def get(self, execution_id: str) -> dict[str, Any]:
        return await self._call("GET", f"/executions/{execution_id}")

    async def result(self, execution_id: str) -> dict[str, Any]:
        return await self._call("GET", f"/executions/{execution_id}/result")

    async def artifacts(self, execution_id: str) -> list[dict[str, Any]]:
        page = await self._call("GET", f"/executions/{execution_id}/artifacts", params={"limit": 200})
        return page["items"]

    async def artifact(self, artifact_id: str) -> dict[str, Any]:
        return await self._call("GET", f"/artifacts/{artifact_id}")

    async def create_report(
        self, execution_id: str, *, idempotency_key: str, markdown: str, name: str, metadata: dict[str, Any]
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
        return await self._call("POST", f"/executions/{execution_id}/artifacts", json=body)

    async def stream_artifact(self, artifact_id: str) -> tuple[httpx.Response, AsyncIterator[bytes]]:
        request = self.http.build_request("GET", f"/artifacts/{artifact_id}/content")
        response = await self.http.send(request, stream=True)
        if response.status_code >= 400:
            await response.aread()
            raise ExecutorError(response.status_code, response.text)
        return response, response.aiter_bytes()
