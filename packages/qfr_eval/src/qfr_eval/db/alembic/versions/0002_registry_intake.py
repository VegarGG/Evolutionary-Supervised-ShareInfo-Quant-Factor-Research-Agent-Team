"""Private immutable campaign/evidence and durable pull cursor, not a public API."""

from pathlib import Path

from alembic import op

revision = "0002_registry_intake"
down_revision = "0001_evaluator_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    raise RuntimeError("Evidence-preserving migration; no destructive downgrade")
