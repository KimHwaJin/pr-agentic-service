"""api_clients: tenants whose batches pr-batch has not turned off yet

Revoking a tenant (or its last active key) asks pr-batch to turn off the
tenant's batches (disable-by-tenant); a failed call is kept here and
retried by the worker.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-01
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_clients",
        sa.Column(
            "batches_disable_pending",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("api_clients", "batches_disable_pending")
