"""runs.model_alias -> runs.model (served model name)

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# aliases used before the model catalog
OLD_ALIASES = {"default": "qwen38-27b-nvfp4", "fp8": "qwen38-27b-fp8"}


def upgrade() -> None:
    op.alter_column("runs", "model_alias", new_column_name="model")
    for alias, name in OLD_ALIASES.items():
        op.execute(f"UPDATE runs SET model = '{name}' WHERE model = '{alias}'")


def downgrade() -> None:
    op.alter_column("runs", "model", new_column_name="model_alias")
