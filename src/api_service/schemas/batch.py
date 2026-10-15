"""pr-batch integration."""

from typing import Any

from api_service.schemas.base import Model


class BatchScriptFromNotebook(Model):
    artifact_id: str
    name: str | None = None


class ReportJobCreate(Model):
    batch_run_id: str
    execution_id: str
    owner_id: str
    options: dict[str, Any] = {}
