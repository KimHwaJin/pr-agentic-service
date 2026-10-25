"""baseline

Squashes the former 0001-0007. A database already at 0007 moves onto
this baseline with:

    CREATE INDEX ix_batch_report_events_created_at
        ON batch_report_events (created_at);
    DROP INDEX ix_run_events_session_id;
    DROP INDEX ix_messages_session_id;
    UPDATE alembic_version SET version_num = '0001';

Revision ID: 0001
Revises:
Create Date: 2026-10-25
"""

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "batch_report_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column(
            "data", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_batch_report_events_created_at"),
        "batch_report_events",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_batch_report_events_job_id"),
        "batch_report_events",
        ["job_id"],
        unique=False,
    )
    op.create_table(
        "batch_report_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("execution_id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=64), nullable=True),
        sa.Column("batch_run_id", sa.String(length=64), nullable=True),
        sa.Column(
            "execution",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("failed_stage", sa.String(length=16), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("markdown", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("artifact_id", sa.String(length=36), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column(
            "lease_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "collecting_since", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        op.f("ix_batch_report_jobs_batch_id"),
        "batch_report_jobs",
        ["batch_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_batch_report_jobs_execution_id"),
        "batch_report_jobs",
        ["execution_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_batch_report_jobs_owner_id"),
        "batch_report_jobs",
        ["owner_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_batch_report_jobs_state"),
        "batch_report_jobs",
        ["state"],
        unique=False,
    )
    op.create_table(
        "code_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("tool_call_id", sa.String(length=128), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("skill", sa.String(length=128), nullable=True),
        sa.Column("tool", sa.String(length=128), nullable=True),
        sa.Column("call_key", sa.String(length=32), nullable=True),
        sa.Column("tool_version", sa.String(length=64), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=True),
        sa.Column("approved_by", sa.String(length=36), nullable=True),
        sa.Column("edited", sa.Boolean(), nullable=True),
        sa.Column("execution_id", sa.String(length=36), nullable=True),
        sa.Column("operation_id", sa.String(length=36), nullable=True),
        sa.Column("step_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "file_deleted_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("path"),
    )
    op.create_index(
        op.f("ix_code_sources_created_at"),
        "code_sources",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_code_sources_execution_id"),
        "code_sources",
        ["execution_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_code_sources_run_id"),
        "code_sources",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_code_sources_session_id"),
        "code_sources",
        ["session_id"],
        unique=False,
    )
    op.create_table(
        "executor_inbox",
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("execution_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("event_sequence", sa.Integer(), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        op.f("ix_executor_inbox_execution_id"),
        "executor_inbox",
        ["execution_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_executor_inbox_received_at"),
        "executor_inbox",
        ["received_at"],
        unique=False,
    )
    op.create_table(
        "images",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=32), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_images_session_id"), "images", ["session_id"], unique=False
    )
    op.create_table(
        "memory_history",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column(
            "before", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "after", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_memory_history_project_id"),
        "memory_history",
        ["project_id"],
        unique=False,
    )
    op.create_table(
        "run_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column(
            "data", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_run_events_created_at"),
        "run_events",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_run_events_session_id_id",
        "run_events",
        ["session_id", "id"],
        unique=False,
    )
    op.create_table(
        "run_requests",
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("resumed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("session_id", "key"),
    )
    op.create_index(
        op.f("ix_run_requests_created_at"),
        "run_requests",
        ["created_at"],
        unique=False,
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("employee_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("english_name", sa.String(length=200), nullable=True),
        sa.Column("department", sa.String(length=200), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("employee_id"),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("code_level", sa.Integer(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "workflows",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("user_request", sa.Text(), nullable=False),
        sa.Column(
            "document", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "user_queries",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("lifecycle", sa.String(length=16), nullable=False),
        sa.Column("author_id", sa.String(length=36), nullable=False),
        sa.Column("source_run_id", sa.String(length=36), nullable=True),
        sa.Column("source_workflow_id", sa.String(length=36), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("index_state", sa.String(length=16), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_workflows_author_id"),
        "workflows",
        ["author_id"],
        unique=False,
    )
    op.create_table(
        "project_members",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("project_id", "user_id"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "title_source",
            sa.String(length=16),
            server_default="initial",
            nullable=False,
        ),
        sa.Column("code_level", sa.Integer(), nullable=True),
        sa.Column("active_run_id", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_sessions_project_id"),
        "sessions",
        ["project_id"],
        unique=False,
    )
    op.create_table(
        "workflow_query_vectors",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column(
            "embedding", pgvector.sqlalchemy.vector.VECTOR(), nullable=False
        ),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_workflow_query_vectors_workflow_id"),
        "workflow_query_vectors",
        ["workflow_id"],
        unique=False,
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "attachments",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_messages_session_created",
        "messages",
        ["session_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column(
            "input", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "resume", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "waiting", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column(
            "lease_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_runs_claim", "runs", ["status", "lease_expires_at"], unique=False
    )
    op.create_index(
        op.f("ix_runs_session_id"), "runs", ["session_id"], unique=False
    )
    op.create_index(op.f("ix_runs_status"), "runs", ["status"], unique=False)
    op.create_index(
        "ix_runs_waiting_execution",
        "runs",
        [sa.literal_column("(waiting ->> 'execution_id')")],
        unique=False,
        postgresql_where=sa.text("status = 'waiting_executor'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_runs_waiting_execution",
        table_name="runs",
        postgresql_where=sa.text("status = 'waiting_executor'"),
    )
    op.drop_index(op.f("ix_runs_status"), table_name="runs")
    op.drop_index(op.f("ix_runs_session_id"), table_name="runs")
    op.drop_index("ix_runs_claim", table_name="runs")
    op.drop_table("runs")
    op.drop_index("ix_messages_session_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index(
        op.f("ix_workflow_query_vectors_workflow_id"),
        table_name="workflow_query_vectors",
    )
    op.drop_table("workflow_query_vectors")
    op.drop_index(op.f("ix_sessions_project_id"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("project_members")
    op.drop_index(op.f("ix_workflows_author_id"), table_name="workflows")
    op.drop_table("workflows")
    op.drop_table("projects")
    op.drop_table("users")
    op.drop_index(
        op.f("ix_run_requests_created_at"), table_name="run_requests"
    )
    op.drop_table("run_requests")
    op.drop_index("ix_run_events_session_id_id", table_name="run_events")
    op.drop_index(op.f("ix_run_events_created_at"), table_name="run_events")
    op.drop_table("run_events")
    op.drop_index(
        op.f("ix_memory_history_project_id"), table_name="memory_history"
    )
    op.drop_table("memory_history")
    op.drop_index(op.f("ix_images_session_id"), table_name="images")
    op.drop_table("images")
    op.drop_index(
        op.f("ix_executor_inbox_received_at"), table_name="executor_inbox"
    )
    op.drop_index(
        op.f("ix_executor_inbox_execution_id"), table_name="executor_inbox"
    )
    op.drop_table("executor_inbox")
    op.drop_index(
        op.f("ix_code_sources_session_id"), table_name="code_sources"
    )
    op.drop_index(op.f("ix_code_sources_run_id"), table_name="code_sources")
    op.drop_index(
        op.f("ix_code_sources_execution_id"), table_name="code_sources"
    )
    op.drop_index(
        op.f("ix_code_sources_created_at"), table_name="code_sources"
    )
    op.drop_table("code_sources")
    op.drop_index(
        op.f("ix_batch_report_jobs_state"), table_name="batch_report_jobs"
    )
    op.drop_index(
        op.f("ix_batch_report_jobs_owner_id"), table_name="batch_report_jobs"
    )
    op.drop_index(
        op.f("ix_batch_report_jobs_execution_id"),
        table_name="batch_report_jobs",
    )
    op.drop_index(
        op.f("ix_batch_report_jobs_batch_id"), table_name="batch_report_jobs"
    )
    op.drop_table("batch_report_jobs")
    op.drop_index(
        op.f("ix_batch_report_events_job_id"), table_name="batch_report_events"
    )
    op.drop_index(
        op.f("ix_batch_report_events_created_at"),
        table_name="batch_report_events",
    )
    op.drop_table("batch_report_events")
