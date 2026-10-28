"""Extend the unchanged Stage 0 registry without rewriting historical evidence."""

from pathlib import Path

from alembic import op

revision = "0001_registry"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    raise RuntimeError(
        "Immutable publications require a reviewed restore, not destructive downgrade"
    )
