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
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, column_property, mapped_column

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
    role: Mapped[str] = mapped_column(
        String(16), default="user"
    )  # user | admin
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
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class ProjectMember(Base):
    """Ownership today; the table already allows sharing a project later."""

    __tablename__ = "project_members"
    project_id: Mapped[str] = mapped_column(
        ID, ForeignKey("projects.id"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        ID, ForeignKey("users.id"), primary_key=True
    )
    role: Mapped[str] = mapped_column(
        String(16), default="owner"
    )  # owner | editor | viewer
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class ChatSession(Timestamped, Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ID, ForeignKey("projects.id"), index=True
    )
    user_id: Mapped[str] = mapped_column(ID, ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200), default="새 대화")
    # initial (from the first message)
    # -> auto (LLM summary after the first answer) | user (renamed)
    title_source: Mapped[str] = mapped_column(
        String(16), default="initial", server_default="initial"
    )
    code_level: Mapped[int | None] = mapped_column(Integer)
    active_run_id: Mapped[str | None] = mapped_column(ID)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    # loaded with the row: the project's level, for the effective level
    project_code_level: Mapped[int | None] = column_property(
        select(Project.code_level)
        .where(Project.id == project_id)
        .correlate_except(Project)
        .scalar_subquery()
    )


class Message(Base):
    """What the chat UI shows.

    The agent's own history lives in the checkpointer.
    """

    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ID, ForeignKey("sessions.id"))
    run_id: Mapped[str | None] = mapped_column(ID)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class Run(Timestamped, Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ID, ForeignKey("sessions.id"), index=True
    )
    project_id: Mapped[str] = mapped_column(ID)
    user_id: Mapped[str] = mapped_column(ID)
    # queued -> running -> (waiting_input | waiting_executor) -> queued ...
    # -> terminal
    status: Mapped[str] = mapped_column(String(24), index=True)
    model: Mapped[str] = mapped_column(String(64))
    input: Mapped[dict[str, Any]] = mapped_column(JSONB)
    resume: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    waiting: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class RunEvent(Base):
    __tablename__ = "run_events"
    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    session_id: Mapped[str] = mapped_column(ID)
    run_id: Mapped[str] = mapped_column(ID)
    type: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class ExecutorInbox(Base):
    """Deduplicated executor events.

    The source a waiting run is resumed from.
    """

    __tablename__ = "executor_inbox"
    event_id: Mapped[str] = mapped_column(ID, primary_key=True)
    execution_id: Mapped[str] = mapped_column(ID, index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    event_sequence: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class MemoryHistory(Base):
    __tablename__ = "memory_history"
    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    project_id: Mapped[str] = mapped_column(ID, index=True)
    item_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(16))  # create | update | delete
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    actor_type: Mapped[str] = mapped_column(String(16))  # user | agent
    actor_id: Mapped[str] = mapped_column(String(64))
    session_id: Mapped[str | None] = mapped_column(ID)
    run_id: Mapped[str | None] = mapped_column(ID)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class Workflow(Timestamped, Base):
    __tablename__ = "workflows"
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    user_request: Mapped[str] = mapped_column(Text)
    document: Mapped[dict[str, Any]] = mapped_column(JSONB)
    user_queries: Mapped[list[str]] = mapped_column(JSONB, default=list)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    lifecycle: Mapped[str] = mapped_column(
        String(16), default="candidate"
    )  # | template
    author_id: Mapped[str] = mapped_column(
        ID, ForeignKey("users.id"), index=True
    )
    source_run_id: Mapped[str | None] = mapped_column(ID)
    source_workflow_id: Mapped[str | None] = mapped_column(ID)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    index_state: Mapped[str] = mapped_column(String(16), default="not_indexed")
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class WorkflowQueryVector(Base):
    __tablename__ = "workflow_query_vectors"
    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    workflow_id: Mapped[str] = mapped_column(
        ID, ForeignKey("workflows.id"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    query: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(200))
    embedding: Mapped[list[float]] = mapped_column(Vector())
    active: Mapped[bool] = mapped_column(Boolean, default=False)


class BatchReportJob(Timestamped, Base):
    """The report of one successful BATCH execution (worker.batch_reports).

    One per execution: ``idempotency_key`` is ``batch-report:{execution_id}``.
    ``owner_id`` is the execution's ``context.user_id`` (users.id); only that
    user sees the job. ``execution`` keeps the trigger/context/metadata the
    job was started from.
    """

    __tablename__ = "batch_report_jobs"
    __table_args__ = (UniqueConstraint("idempotency_key"),)
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    execution_id: Mapped[str] = mapped_column(ID, index=True)
    batch_id: Mapped[str | None] = mapped_column(String(64), index=True)
    batch_run_id: Mapped[str | None] = mapped_column(String(64))
    execution: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # QUEUED -> COLLECTING -> GENERATING -> MATERIALIZING -> SUCCEEDED | FAILED
    state: Mapped[str] = mapped_column(
        String(16), default="QUEUED", index=True
    )
    failed_stage: Mapped[str | None] = mapped_column(String(16))
    title: Mapped[str | None] = mapped_column(String(200))
    markdown: Mapped[str | None] = mapped_column(Text)
    # what the next run of the batch reads (batch memory)
    summary: Mapped[str | None] = mapped_column(Text)
    artifact_id: Mapped[str | None] = mapped_column(ID)
    error: Mapped[str | None] = mapped_column(Text)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    # also "not before" while COLLECTING waits for the notebook
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    # start of the current wait for the notebook (a retry waits anew)
    collecting_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class BatchReportEvent(Base):
    """Progress of a report job, in the chat event format.

    ``{id, type, run_id=job id, data}`` with the types of
    ``core.contracts.events`` so the chat components draw a job too.
    """

    __tablename__ = "batch_report_events"
    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    job_id: Mapped[str] = mapped_column(ID, index=True)
    type: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


Index("ix_runs_claim", Run.status, Run.lease_expires_at)
# executor events look up the run waiting on an execution
Index(
    "ix_runs_waiting_execution",
    Run.waiting["execution_id"].astext,
    postgresql_where=Run.status == "waiting_executor",
)
# SSE replay reads a session's events after a cursor
Index("ix_run_events_session_id_id", RunEvent.session_id, RunEvent.id)
Index("ix_messages_session_created", Message.session_id, Message.created_at)


class CodeSource(Base):
    """One code file sent to the executor (a step of an operation).

    The file is only the transport: the executor snapshots it at submit,
    and that snapshot plus the notebook are the record of what ran. This
    row ties the file to its run and to the executor step.
    """

    __tablename__ = "code_sources"
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ID)
    project_id: Mapped[str] = mapped_column(ID)
    session_id: Mapped[str] = mapped_column(ID, index=True)
    run_id: Mapped[str] = mapped_column(ID, index=True)
    tool_call_id: Mapped[str] = mapped_column(String(128))
    # executor-relative path; also the idempotent key of the row
    path: Mapped[str] = mapped_column(String(1024), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))  # setup | tool | custom
    skill: Mapped[str | None] = mapped_column(String(128))
    tool: Mapped[str | None] = mapped_column(String(128))
    call_key: Mapped[str | None] = mapped_column(String(32))
    tool_version: Mapped[str | None] = mapped_column(String(64))
    purpose: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(ID)
    edited: Mapped[bool | None] = mapped_column(Boolean)
    execution_id: Mapped[str | None] = mapped_column(ID, index=True)
    operation_id: Mapped[str | None] = mapped_column(ID)
    step_id: Mapped[str | None] = mapped_column(ID)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    file_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class Image(Base):
    """An image a user sent with a turn (stored once, referenced by id)."""

    __tablename__ = "images"
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ID)
    project_id: Mapped[str] = mapped_column(ID)
    session_id: Mapped[str] = mapped_column(ID, index=True)
    run_id: Mapped[str | None] = mapped_column(ID)
    name: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(32))
    size_bytes: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(String(1024))  # under STORAGE_ROOT
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class RunRequest(Base):
    """Idempotency-Key of POST /sessions/{id}/runs (kept for a day)."""

    __tablename__ = "run_requests"
    session_id: Mapped[str] = mapped_column(ID, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[str] = mapped_column(ID)
    resumed: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
