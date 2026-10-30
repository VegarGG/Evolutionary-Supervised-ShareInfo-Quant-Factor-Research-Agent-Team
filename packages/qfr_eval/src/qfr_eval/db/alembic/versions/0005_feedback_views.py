"""Serve only committed release publications and explicit public cards."""

from pathlib import Path

from alembic import op

revision = "0005_feedback_views"
down_revision = "0004_release_history_guards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    raise RuntimeError("Released visibility and cursor identities cannot be downgraded")
