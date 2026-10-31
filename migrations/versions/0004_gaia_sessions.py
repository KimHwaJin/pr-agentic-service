"""gaia_sessions

This was 0002 before main's 0002 and 0003. A database upgraded with that
earlier 0002 has the table but not main's 0002 and 0003; it moves on with

    UPDATE alembic_version SET version_num = '0001';

and an upgrade, which keeps the existing table.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("gaia_sessions"):
        return
    op.create_table(
        "gaia_sessions",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("gaia_session_id", sa.String(length=200), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "gaia_session_id"),
    )


def downgrade() -> None:
    op.drop_table("gaia_sessions")
