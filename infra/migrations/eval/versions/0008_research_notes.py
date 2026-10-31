"""Phase 8 eval_db (PLAN Sections 7.6 and 8.10, P8.2): research notes.

A research note is checked for output quality at intake and released as a note report.
Its intake row ends in NoteChecked (every check passed) or NoteFailed; it is never
screened, measured on a window or simulated.
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

INTAKE_STATES = (
    "Discovered",
    "Held",
    "Fingerprinting",
    "Deferred",
    "Screening",
    "IntakeRejected",
    "Duplicate",
    "ScreenFailed",
    "W1Evaluated",
    "W1GateFailed",
    "W2Queued",
    "W2Failed",
    "W2Expired",
    "HoldoutCheck",
    "NotAdvanced",
    "AwaitingSlot",
    "Incubating",
    "AcceptanceReview",
    "Accepted",
    "Rejected",
    "Monitoring",
    "Retired",
    "NoteChecked",
    "NoteFailed",
)
REPORT_TYPES = (
    "intake",
    "screening",
    "w1",
    "w2",
    "advancement",
    "sim",
    "decision",
    "library",
    "note",
)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _check(table: str, name: str, condition: str) -> None:
    op.execute(f"ALTER TABLE eval.{table} DROP CONSTRAINT {name}")
    op.execute(f"ALTER TABLE eval.{table} ADD CONSTRAINT {name} CHECK ({condition})")


def upgrade():
    _check("intake", "intake_state_check", f"state IN ({_in(INTAKE_STATES)})")
    _check(
        "release_queue", "release_queue_report_type_check", f"report_type IN ({_in(REPORT_TYPES)})"
    )
    _check(
        "released_reports",
        "released_reports_report_type_check",
        f"report_type IN ({_in(REPORT_TYPES)})",
    )


def downgrade():
    raise RuntimeError("Evaluation migrations are append-only; restore into a new database.")
