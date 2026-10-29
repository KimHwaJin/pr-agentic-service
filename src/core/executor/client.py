import logging
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import datetime
from typing import Any

import httpx

from core.service_headers import SYSTEM, Identity, with_key

log = logging.getLogger(__name__)

SERVICE_ACTOR = {"type": "AGENT", "id": "pr-agentic-service"}


def trigger_type(execution: dict[str, Any]) -> str | None:
    """INTERACTIVE | BATCH of an execution or an event's ``execution``."""
    return (execution.get("trigger") or {}).get("type")


__all__ = ["SYSTEM", "ExecutorClient", "ExecutorError", "Identity"]


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

    Every request carries our API key (``X-Api-Key``) and the identity it
    is made for (``Identity.headers``); the executor scopes executions to
    that tenant and user. Every mutation carries a caller-derived
    idempotency key so a replayed call (pod crash, graph replay) returns
    the original receipt.

    ``tenant`` (our ``EXECUTOR_TENANT_ID``) goes as ``X-Tenant-Id`` on every
    call that names no other: an executor in header mode (local/dev) has no
    key to take it from and would file our executions under its default.
    """

    def __init__(
        self,
        base_url: str,
        timeout: float,
        api_key: str = "",
        admin_api_key: str = "",
        tenant: str = "",
    ):
        self.tenant = tenant
        self.http = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/api/v1", timeout=timeout
        )
        self.api_key, self.admin_api_key = api_key, admin_api_key

    async def close(self) -> None:
        await self.http.aclose()

    def headers(
        self, who: Identity = SYSTEM, admin: bool = False
    ) -> dict[str, str]:
        """Key and identity headers of one request.

        ``admin``: the operator key of the runtime and maintenance APIs.
        """
        if admin:  # operator APIs act for no tenant
            return with_key(self.admin_api_key, who)
        if who.tenant is None and self.tenant:
            who = replace(who, tenant=self.tenant)
        return with_key(self.api_key, who)

    async def _call(
        self, method: str, url: str, who: Identity = SYSTEM, **kwargs: Any
    ) -> Any:
        response = await self.http.request(
            method, url, headers=self.headers(who), **kwargs
        )
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
        who: Identity,
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
            "lifecycle": lifecycle,
            "trigger": {"type": trigger, "actor": SERVICE_ACTOR},
            "runtime": {"type": "JUPYTER", "profile": profile},
            "operation": {"spec": {"schema_version": "1.0", "steps": steps}},
            "metadata": metadata or {},
        }
        return await self._call("POST", "/executions", who, json=body)

    async def append_operation(
        self,
        execution_id: str,
        *,
        who: Identity,
        idempotency_key: str,
        expected_version: int,
        steps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        body = {
            "idempotency_key": idempotency_key,
            "expected_version": expected_version,
            "spec": {"schema_version": "1.0", "steps": steps},
            "actor": SERVICE_ACTOR,
        }
        return await self._call(
            "POST", f"/executions/{execution_id}/operations", who, json=body
        )

    async def finalize(
        self,
        execution_id: str,
        *,
        who: Identity,
        idempotency_key: str,
        expected_version: int,
    ) -> dict[str, Any]:
        body = {
            "idempotency_key": idempotency_key,
            "expected_version": expected_version,
            "actor": SERVICE_ACTOR,
        }
        return await self._call(
            "POST", f"/executions/{execution_id}/finalize", who, json=body
        )

    async def cancel(
        self,
        execution_id: str,
        *,
        who: Identity,
        idempotency_key: str,
        reason: str,
    ) -> dict[str, Any]:
        body = {
            "idempotency_key": idempotency_key,
            "reason": reason,
            "actor": SERVICE_ACTOR,
        }
        return await self._call(
            "POST", f"/executions/{execution_id}/cancel", who, json=body
        )

    async def get(self, execution_id: str) -> dict[str, Any]:
        return await self._call("GET", f"/executions/{execution_id}")

    async def opener(self, execution_id: str) -> Identity:
        """The identity an execution answers to (its ``context``).

        For mutations on an execution this service did not open in the same
        call path (cancel from another member, a batch execution's report).
        """
        context = (await self.get(execution_id)).get("context") or {}
        return Identity(
            user_id=context.get("user_id"),
            project_id=context.get("project_id"),
            session_id=context.get("session_id"),
        )

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

        A system read: the executions of our tenant, any user. ``filters``
        are the list's query parameters (``trigger_type``, ``status``,
        ``project_id``, ...). The list has no time filter, so pages are read
        until they pass ``created_after``.
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
        who: Identity,
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
            "actor": SERVICE_ACTOR,
        }
        return await self._call(
            "POST", f"/executions/{execution_id}/artifacts", who, json=body
        )

    async def stream_artifact(
        self, artifact_id: str
    ) -> tuple[httpx.Response, AsyncIterator[bytes]]:
        request = self.http.build_request(
            "GET", f"/artifacts/{artifact_id}/content", headers=self.headers()
        )
        response = await self.http.send(request, stream=True)
        if response.status_code >= 400:
            await response.aread()
            raise ExecutorError(response.status_code, response.text)
        return response, response.aiter_bytes()
