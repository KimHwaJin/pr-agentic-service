from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class UserRead(Model):
    id: str
    employee_id: str
    name: str
    english_name: str | None
    department: str | None
    email: str | None
    role: str
    is_active: bool


class UserAdminUpdate(Model):
    role: Literal["user", "admin"] | None = None
    is_active: bool | None = None


class ProjectCreate(Model):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    system_prompt: str = Field("", max_length=8000)
    code_level: int | None = Field(None, ge=1, le=4)


class ProjectUpdate(Model):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    system_prompt: str | None = Field(None, max_length=8000)
    code_level: int | None = Field(None, ge=1, le=4)


class ProjectRead(Model):
    id: str
    name: str
    description: str
    system_prompt: str
    code_level: int | None
    is_default: bool
    created_at: datetime
    updated_at: datetime


class SessionCreate(Model):
    title: str | None = Field(None, max_length=200)
    code_level: int | None = Field(None, ge=1, le=4)
    message: str | None = Field(None, min_length=1, max_length=20000, description="첫 메시지. 있으면 바로 run 시작")
    model_alias: str | None = None


class SessionUpdate(Model):
    title: str | None = Field(None, min_length=1, max_length=200)
    code_level: int | None = Field(None, ge=1, le=4)


class SessionRead(Model):
    id: str
    project_id: str
    title: str
    title_source: str
    code_level: int | None
    active_run_id: str | None
    created_at: datetime
    updated_at: datetime


class MessageCreate(Model):
    content: str = Field(min_length=1, max_length=20000)
    model_alias: str | None = None


class MessageRead(Model):
    id: str
    run_id: str | None
    role: str
    content: str
    attachments: list[dict[str, Any]]
    created_at: datetime


class RunRead(Model):
    id: str
    session_id: str
    status: str
    model_alias: str
    waiting: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class SessionStart(Model):
    session: SessionRead
    run: RunRead | None


class ResumeRequest(Model):
    interrupt_id: str
    value: Any


class MemoryCreate(Model):
    category: Literal["background", "analysis_preferences", "report_preferences", "shared_findings"]
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)


class MemoryUpdate(Model):
    expected_version: int
    category: Literal["background", "analysis_preferences", "report_preferences", "shared_findings"] | None = None
    title: str | None = Field(None, min_length=1, max_length=200)
    content: str | None = Field(None, min_length=1)


class WorkflowCreate(Model):
    document: dict[str, Any]
    user_queries: list[str] = Field(min_length=1)
    tags: list[str] = []
    source_run_id: str | None = None


class WorkflowUpdate(Model):
    expected_revision: int
    document: dict[str, Any] | None = None
    user_queries: list[str] | None = None
    tags: list[str] | None = None


class WorkflowRead(Model):
    id: str
    name: str
    user_request: str
    lifecycle: str
    document: dict[str, Any]
    user_queries: list[str]
    tags: list[str]
    author_id: str
    source_run_id: str | None
    source_workflow_id: str | None
    revision: int
    index_state: str
    created_at: datetime
    updated_at: datetime


class WorkflowSummary(Model):
    """List item: no document, only what a card needs."""

    id: str
    name: str
    user_request: str
    lifecycle: str
    tags: list[str]
    author_id: str
    revision: int
    index_state: str
    steps: list[dict[str, Any]]  # [{skill, tools: [{tool, execution}]}] in execution order
    call_count: int
    mine: bool
    created_at: datetime
    updated_at: datetime


class WorkflowDetail(WorkflowRead):
    calls: list[dict[str, Any]]  # per tool call: skill, tool, summary, condition, params with sources and docs
    mine: bool


class WorkflowClone(Model):
    name: str | None = None


class WorkflowSearch(Model):
    query: str = Field(min_length=1, max_length=4000)


class BatchScriptFromNotebook(Model):
    artifact_id: str
    name: str | None = None


class ReportJobCreate(Model):
    batch_run_id: str
    execution_id: str
    owner_id: str
    options: dict[str, Any] = {}
