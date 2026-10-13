from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base, Timestamped, new_id, utcnow

ID = String(36)


class User(Timestamped, Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    employee_id: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    english_name: Mapped[str | None] = mapped_column(String(200))
    department: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(16), default="user")  # user | admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Project(Timestamped, Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    code_level: Mapped[int | None] = mapped_column(Integer)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(ID, ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectMember(Base):
    """Ownership today; the table already allows sharing a project later."""

    __tablename__ = "project_members"
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ID, ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), default="owner")  # owner | editor | viewer
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChatSession(Timestamped, Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), index=True)
    user_id: Mapped[str] = mapped_column(ID, ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200), default="새 대화")
    code_level: Mapped[int | None] = mapped_column(Integer)
    active_run_id: Mapped[str | None] = mapped_column(ID)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(Base):
    """What the chat UI shows. The agent's own history lives in the checkpointer."""

    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ID, ForeignKey("sessions.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(ID)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Run(Timestamped, Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ID, ForeignKey("sessions.id"), index=True)
    project_id: Mapped[str] = mapped_column(ID)
    user_id: Mapped[str] = mapped_column(ID)
    # queued -> running -> (waiting_input | waiting_executor) -> queued ... -> terminal
    status: Mapped[str] = mapped_column(String(24), index=True)
    model_alias: Mapped[str] = mapped_column(String(64))
    input: Mapped[dict[str, Any]] = mapped_column(JSONB)
    resume: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    waiting: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunEvent(Base):
    __tablename__ = "run_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ID, index=True)
    run_id: Mapped[str] = mapped_column(ID)
    type: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExecutorInbox(Base):
    """Deduplicated executor events; the source a waiting run is resumed from."""

    __tablename__ = "executor_inbox"
    event_id: Mapped[str] = mapped_column(ID, primary_key=True)
    execution_id: Mapped[str] = mapped_column(ID, index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    event_sequence: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MemoryHistory(Base):
    __tablename__ = "memory_history"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ID, index=True)
    item_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(16))  # create | update | delete
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    actor_type: Mapped[str] = mapped_column(String(16))  # user | agent
    actor_id: Mapped[str] = mapped_column(String(64))
    session_id: Mapped[str | None] = mapped_column(ID)
    run_id: Mapped[str | None] = mapped_column(ID)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Workflow(Timestamped, Base):
    __tablename__ = "workflows"
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    user_request: Mapped[str] = mapped_column(Text)
    document: Mapped[dict[str, Any]] = mapped_column(JSONB)
    user_queries: Mapped[list[str]] = mapped_column(JSONB, default=list)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    lifecycle: Mapped[str] = mapped_column(String(16), default="candidate")  # | template
    author_id: Mapped[str] = mapped_column(ID, ForeignKey("users.id"), index=True)
    source_run_id: Mapped[str | None] = mapped_column(ID)
    source_workflow_id: Mapped[str | None] = mapped_column(ID)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    index_state: Mapped[str] = mapped_column(String(16), default="not_indexed")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowQueryVector(Base):
    __tablename__ = "workflow_query_vectors"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workflow_id: Mapped[str] = mapped_column(ID, ForeignKey("workflows.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    query: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(200))
    embedding: Mapped[list[float]] = mapped_column(Vector())
    active: Mapped[bool] = mapped_column(Boolean, default=False)


class BatchReportJob(Timestamped, Base):
    __tablename__ = "batch_report_jobs"
    __table_args__ = (UniqueConstraint("idempotency_key"),)
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    owner_id: Mapped[str] = mapped_column(String(64))
    execution_id: Mapped[str] = mapped_column(ID)
    batch_run_id: Mapped[str] = mapped_column(String(64))
    request: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # QUEUED -> COLLECTING -> GENERATING -> MATERIALIZING -> SUCCEEDED | FAILED
    state: Mapped[str] = mapped_column(String(16), default="QUEUED", index=True)
    failed_stage: Mapped[str | None] = mapped_column(String(16))
    markdown: Mapped[str | None] = mapped_column(Text)
    artifact_id: Mapped[str | None] = mapped_column(ID)
    error: Mapped[str | None] = mapped_column(Text)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index("ix_runs_claim", Run.status, Run.lease_expires_at)
