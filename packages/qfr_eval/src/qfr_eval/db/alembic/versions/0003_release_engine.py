"""Evaluator-owned policy, immutable quota allocations and private release queue."""

from pathlib import Path

from alembic import op

revision = "0003_release_engine"
down_revision = "0002_registry_intake"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    raise RuntimeError("Release history is immutable; no destructive downgrade")
