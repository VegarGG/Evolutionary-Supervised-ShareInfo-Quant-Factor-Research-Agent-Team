"""Extend the Stage 0 reservations without modifying existing evidence."""

from pathlib import Path

from alembic import op

revision = "0001_blackboard"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    raise RuntimeError("Evidence-preserving migration: use a reviewed backup, no destructive down")
