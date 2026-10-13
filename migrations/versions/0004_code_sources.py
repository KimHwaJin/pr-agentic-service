"""code sources sent to the executor

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "code_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("tool_call_id", sa.String(128), nullable=False),
        sa.Column("path", sa.String(1024), nullable=False, unique=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("skill", sa.String(128)),
        sa.Column("tool", sa.String(128)),
        sa.Column("call_key", sa.String(32)),
        sa.Column("tool_version", sa.String(64)),
        sa.Column("purpose", sa.Text),
        sa.Column("approved_by", sa.String(36)),
        sa.Column("edited", sa.Boolean),
        sa.Column("execution_id", sa.String(36)),
        sa.Column("operation_id", sa.String(36)),
        sa.Column("step_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("file_deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_code_sources_run_id", "code_sources", ["run_id"])
    op.create_index(
        "ix_code_sources_session_id", "code_sources", ["session_id"]
    )
    op.create_index(
        "ix_code_sources_execution_id", "code_sources", ["execution_id"]
    )
    op.create_index(
        "ix_code_sources_created_at", "code_sources", ["created_at"]
    )


def downgrade() -> None:
    op.drop_table("code_sources")
