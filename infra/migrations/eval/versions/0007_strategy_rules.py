"""Phase 8 eval_db (PLAN Section 7.8, P8.2): simulation of qfr-strategy/2 books.

A long-short strategy holds short positions, stored as negative share counts, and its
orders gain the reasons short_entry, cover and cover_pending; a position cap adds trim
orders. Long-only books keep writing exactly what they wrote before.
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

REASONS = ("entry", "dropout", "pending", "short_entry", "cover", "cover_pending", "trim")


def upgrade():
    op.execute("ALTER TABLE eval.sim_positions DROP CONSTRAINT sim_positions_shares_check")
    op.execute(
        "ALTER TABLE eval.sim_positions ADD CONSTRAINT sim_positions_shares_check "
        "CHECK (shares <> 0)"
    )
    op.execute("ALTER TABLE eval.sim_orders DROP CONSTRAINT sim_orders_reason_check")
    reasons = ", ".join(f"'{r}'" for r in REASONS)
    op.execute(
        "ALTER TABLE eval.sim_orders ADD CONSTRAINT sim_orders_reason_check "
        f"CHECK (reason IN ({reasons}))"
    )


def downgrade():
    raise RuntimeError("Evaluation migrations are append-only; restore into a new database.")
