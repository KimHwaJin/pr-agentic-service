"""batch reports started from executor events, their progress events

pr-batch no longer asks for reports: a job is made per successful BATCH
execution, owned by the execution's user (users.id).

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("batch_report_jobs", "request_hash")
    op.alter_column(
        "batch_report_jobs", "request", new_column_name="execution"
    )
    op.alter_column(
        "batch_report_jobs",
        "batch_run_id",
        existing_type=sa.String(64),
        nullable=True,
    )
    op.add_column("batch_report_jobs", sa.Column("batch_id", sa.String(64)))
    op.add_column("batch_report_jobs", sa.Column("title", sa.String(200)))
    op.add_column("batch_report_jobs", sa.Column("summary", sa.Text))
    for column in ("collecting_since", "finished_at"):
        op.add_column(
            "batch_report_jobs",
            sa.Column(column, sa.DateTime(timezone=True)),
        )
    for column in ("owner_id", "execution_id", "batch_id"):
        op.create_index(
            f"ix_batch_report_jobs_{column}", "batch_report_jobs", [column]
        )
    op.create_table(
        "batch_report_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column(
            "data", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_batch_report_events_job_id", "batch_report_events", ["job_id"]
    )


def downgrade() -> None:
    op.drop_table("batch_report_events")
    for column in ("owner_id", "execution_id", "batch_id"):
        op.drop_index(
            f"ix_batch_report_jobs_{column}", table_name="batch_report_jobs"
        )
    for column in (
        "finished_at",
        "collecting_since",
        "summary",
        "title",
        "batch_id",
    ):
        op.drop_column("batch_report_jobs", column)
    op.execute(
        "UPDATE batch_report_jobs SET batch_run_id = '' "
        "WHERE batch_run_id IS NULL"
    )
    op.alter_column(
        "batch_report_jobs",
        "batch_run_id",
        existing_type=sa.String(64),
        nullable=False,
    )
    op.alter_column(
        "batch_report_jobs", "execution", new_column_name="request"
    )
    op.add_column(
        "batch_report_jobs",
        sa.Column(
            "request_hash", sa.String(64), nullable=False, server_default=""
        ),
    )
