"""Phase 8 control_db (P8.7): approvals for the owner override of an acceptance case.

An override takes two approvals: override_case starts the 24-hour cooling period and
confirm_override, recorded after it, accepts the case. Both quote the case's short code.
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

DECISIONS = (
    "'approve', 'reject', 'retire', 'accept_case', 'reject_case', 'rollover_epoch', "
    "'override_case', 'confirm_override'"
)


def upgrade():
    op.execute("ALTER TABLE approvals DROP CONSTRAINT approvals_decision_check")
    op.execute(
        "ALTER TABLE approvals ADD CONSTRAINT approvals_decision_check "
        f"CHECK (decision IN ({DECISIONS}))"
    )


def downgrade():
    raise RuntimeError("Control migrations are append-only; restore into a new database.")
