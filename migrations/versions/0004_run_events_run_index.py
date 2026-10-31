"""run_events by run; when missed-event recovery last looked at a run

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # GET /runs/{id}/events and the end-of-turn artifact lookup
    op.create_index("ix_run_events_run_id_id", "run_events", ["run_id", "id"])
    op.add_column(
        "runs",
        sa.Column(
            "recovery_checked_at", sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("runs", "recovery_checked_at")
    op.drop_index("ix_run_events_run_id_id", table_name="run_events")
