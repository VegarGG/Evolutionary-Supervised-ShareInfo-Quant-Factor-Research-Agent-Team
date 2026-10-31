"""Phase 8 eval_db (PLAN Section 10.6, P8.4): epoch rollover.

An epoch now names the epoch it followed and keeps the rollover's report (both written
once, when it is activated; the guard still refuses any later change but retirement).

Queue jobs belong to an epoch: a version that restarts its lifecycle in a new epoch is
queued again there, so a job is unique per kind, version and epoch. Jobs still queued
for a retired epoch end as cancelled, and a running one is cancelled by the worker's
write fence instead of writing into the retired epoch.

Library members are re-measured on the new W1 once ('remeasure' jobs). The run and its
official record have the stage 'remeasure': the library gate reads them like a W1
record, but they are not trials, so they never enter the trial ledger, the burn meters
or the released reports.
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

JOB_KINDS = ("fingerprint", "evaluate", "w2", "holdout", "remeasure")
JOB_STATES = ("queued", "running", "done", "failed", "cancelled")
STAGES = ("screening", "w1", "w2", "holdout", "simulation", "remeasure")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _check(table: str, name: str, condition: str) -> None:
    op.execute(f"ALTER TABLE eval.{table} DROP CONSTRAINT {name}")
    op.execute(f"ALTER TABLE eval.{table} ADD CONSTRAINT {name} CHECK ({condition})")


def upgrade():
    op.execute("""ALTER TABLE eval.epochs
        ADD COLUMN previous_epoch_id text REFERENCES eval.epochs (epoch_id),
        ADD COLUMN rollover jsonb""")

    op.execute("ALTER TABLE eval.queue_jobs ADD COLUMN epoch_id text")
    # Before Phase 8 there was only ever one epoch: every job belongs to it.
    op.execute("""UPDATE eval.queue_jobs SET epoch_id = COALESCE(
        payload ->> 'epoch_id',
        (SELECT epoch_id FROM eval.epochs WHERE status = 'active'),
        (SELECT epoch_id FROM eval.epochs ORDER BY activated_at DESC LIMIT 1))""")
    op.execute("""ALTER TABLE eval.queue_jobs
        ALTER COLUMN epoch_id SET NOT NULL,
        ADD CONSTRAINT queue_jobs_epoch_fk FOREIGN KEY (epoch_id)
            REFERENCES eval.epochs (epoch_id)""")
    op.execute("ALTER TABLE eval.queue_jobs DROP CONSTRAINT queue_jobs_kind_version_id_key")
    op.execute("""ALTER TABLE eval.queue_jobs ADD CONSTRAINT queue_jobs_kind_version_epoch_key
        UNIQUE (kind, version_id, epoch_id)""")
    _check("queue_jobs", "queue_jobs_kind_check", f"kind IN ({_in(JOB_KINDS)})")
    _check("queue_jobs", "queue_jobs_state_check", f"state IN ({_in(JOB_STATES)})")
    _check("runs", "runs_stage_check", f"stage IN ({_in(STAGES)})")
    _check("official_records", "official_records_stage_check", f"stage IN ({_in(STAGES)})")


def downgrade():
    raise RuntimeError("Evaluation migrations are append-only; restore into a new database.")
