"""Workflow templates."""

from datetime import datetime
from typing import Any

from pydantic import Field

from src.dtest.api_service.schemas.base import Model


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
    steps: list[
        dict[str, Any]
    ]  # [{skill, tools: [{tool, execution}]}] in execution order
    call_count: int
    mine: bool
    can_promote: bool  # a candidate this caller may promote
    created_at: datetime
    updated_at: datetime


class WorkflowDetail(WorkflowRead):
    # per tool call: skill, tool, summary, condition, params with sources
    # and docs
    calls: list[dict[str, Any]]
    mine: bool
    can_promote: bool


class WorkflowClone(Model):
    name: str | None = None


class WorkflowSearch(Model):
    query: str = Field(min_length=1, max_length=4000)
