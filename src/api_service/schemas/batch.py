"""pr-batch integration and batch report jobs."""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from api_service.schemas.base import Model
from core.contracts.events import StoredEvent

BatchReportState = Literal[
    "QUEUED",
    "COLLECTING",  # waiting for the executor's notebook
    "GENERATING",  # the agent writes the report
    "MATERIALIZING",  # saving it as an executor artifact
    "SUCCEEDED",
    "FAILED",
]


class BatchScriptFromNotebook(Model):
    artifact_id: str
    name: str | None = None


class BatchReportOwner(Model):
    id: str
    employee_id: str
    name: str


class BatchReportRead(Model):
    id: str
    execution_id: str
    batch_id: str | None
    batch_run_id: str | None = Field(description="pr-batch run (task_id)")
    state: BatchReportState
    failed_stage: str | None = Field(description="FAILED일 때 멈춘 단계")
    title: str | None
    artifact_id: str | None = Field(
        description="리포트 artifact (/api/v1/artifacts/{id})"
    )
    error: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class BatchReportDetail(BatchReportRead):
    owner: BatchReportOwner
    markdown: str | None
    summary: str | None = Field(description="다음 실행이 비교할 요약")
    execution: dict[str, Any] = Field(
        description="작업을 만든 executor 실행의 trigger, context, metadata"
    )


class BatchReportPage(Model):
    items: list[BatchReportRead]
    next_cursor: str | None


class BatchReportEvents(Model):
    report_id: str
    state: BatchReportState
    items: list[StoredEvent] = Field(
        description="채팅 run 이벤트와 같은 모양 (run_id = report id)"
    )
