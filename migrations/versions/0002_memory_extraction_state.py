"""memory_extraction_state: cursor and lease of the memory worker

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_extraction_state",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column(
            "processed_until_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "processed_until_id",
            sa.String(length=36),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "dirty", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "last_activity_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "pending_turns", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column(
            "lease_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "attempts", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("project_id"),
    )
    op.create_index(
        "ix_memory_extraction_claim",
        "memory_extraction_state",
        ["last_activity_at"],
        unique=False,
        postgresql_where=sa.text("dirty"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_memory_extraction_claim", table_name="memory_extraction_state"
    )
    op.drop_table("memory_extraction_state")
