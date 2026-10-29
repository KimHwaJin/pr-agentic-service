"""PATH steps sent INLINE (test environments only; see the package)."""

from typing import Any

from core.executor.client import ExecutorClient
from core.executor.storage import SharedStorage


class InlineExecutorClient(ExecutorClient):
    """ExecutorClient whose PATH sources travel as INLINE content.

    Callers keep their PATH steps (``CodeSources.link`` reads
    ``payload.source.path``); only the request body is rewritten.
    """

    def __init__(
        self,
        base_url: str,
        timeout: float,
        api_key: str,
        storage: SharedStorage,
        tenant: str = "",
    ):
        super().__init__(base_url, timeout, api_key, tenant=tenant)
        self.storage = storage

    async def submit(
        self, *, steps: list[dict[str, Any]], **kwargs: Any
    ) -> dict[str, Any]:
        return await super().submit(steps=self.inline(steps), **kwargs)

    async def append_operation(
        self,
        execution_id: str,
        *,
        steps: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await super().append_operation(
            execution_id, steps=self.inline(steps), **kwargs
        )

    def inline(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Copies of ``steps``; the originals are left untouched."""
        return [self._inline_step(step) for step in steps]

    def _inline_step(self, step: dict[str, Any]) -> dict[str, Any]:
        payload = step.get("payload") or {}
        source = payload.get("source") or {}
        if source.get("type") != "PATH":
            return step
        # no sha256: the executor's INLINE source forbids extra fields
        inline = {"type": "INLINE", "content": self.read(source["path"])}
        return {**step, "payload": {**payload, "source": inline}}

    def read(self, executor_path: str) -> str:
        """Our copy of a file sent as ``executor_path``."""
        prefix = "/".join(
            p for p in (self.storage.executor_path, "sources") if p
        )
        if not executor_path.startswith(prefix + "/"):
            raise ValueError(f"not a source of this service: {executor_path}")
        relative = executor_path[len(prefix) + 1 :]
        return self.storage.source_file(relative).read_text("utf-8")
