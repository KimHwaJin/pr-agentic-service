"""api_clients: a key is active once issued (tenant approval is ours alone)

The executor and pr-batch allow our keys every tenant since 2026-11-01, so
the pending state (waiting for their allowed_tenants deploy) is gone.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-01
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE api_clients SET status = 'active' WHERE status = 'pending'"
    )


def downgrade() -> None:
    pass  # which keys were pending is not kept
