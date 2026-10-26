"""Extend the unchanged Stage 0 baseline; preserve existing evidence rows."""

from pathlib import Path

from alembic import op

revision = "0001_evaluator_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    raise RuntimeError(
        "Evidence-preserving migration: restore a reviewed backup; no destructive down"
    )
