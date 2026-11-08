"""api_clients: standard (일반) and master (마스터) keys

Gateway reads of a standard key see only what its X-User-Id owns; a master
key reads the whole tenant, a user_id query narrowing it. Keys issued
before are standard.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-08
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_clients",
        sa.Column(
            "kind",
            sa.String(16),
            nullable=False,
            server_default="standard",
        ),
    )


def downgrade() -> None:
    op.drop_column("api_clients", "kind")
