"""hot path indexes

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # executor events look up the run waiting on an execution
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_runs_waiting_execution ON runs ((waiting->>'execution_id')) "
        "WHERE status = 'waiting_executor'"
    )
    # SSE replay reads a session's events after a cursor
    op.create_index("ix_run_events_session_id_id", "run_events", ["session_id", "id"])
    op.create_index("ix_run_events_created_at", "run_events", ["created_at"])
    op.create_index("ix_executor_inbox_received_at", "executor_inbox", ["received_at"])
    op.create_index("ix_messages_session_created", "messages", ["session_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_messages_session_created", "messages")
    op.drop_index("ix_executor_inbox_received_at", "executor_inbox")
    op.drop_index("ix_run_events_created_at", "run_events")
    op.drop_index("ix_run_events_session_id_id", "run_events")
    op.execute("DROP INDEX IF EXISTS ix_runs_waiting_execution")
