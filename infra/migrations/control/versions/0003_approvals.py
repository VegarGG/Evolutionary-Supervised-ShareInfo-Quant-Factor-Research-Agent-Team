"""Phase 6 control_db: approval records (PLAN Sections 10.5, 13.5 and 16.4).

Approvals are the record of the owner's decisions. They are insert-only: the front door
creates one from the owner's verbatim confirmation, and pool writes, acceptance
decisions and job closes reference it by id. The front door's trace steps gain the
owner-side step types of Section 14.3, APPROVAL_RECORDED and POOL_EVENT.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

DECISIONS = "'approve', 'reject', 'retire', 'accept_case', 'reject_case', 'rollover_epoch'"
STEP_TYPES = "'DSL_VALIDATED', 'SEEDS_PUBLISHED', 'APPROVAL_RECORDED', 'POOL_EVENT'"


def upgrade():
    op.execute(f"""CREATE TABLE approvals (
        approval_id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        decision text NOT NULL CHECK (decision IN ({DECISIONS})),
        scope jsonb NOT NULL,
        owner_confirmation text NOT NULL CHECK (length(owner_confirmation) BETWEEN 1 AND 2000),
        rationale text NOT NULL CHECK (length(rationale) >= 1),
        short_codes_matched text[] NOT NULL CHECK (cardinality(short_codes_matched) >= 1),
        principal text NOT NULL,
        request_id text NOT NULL,
        record jsonb NOT NULL
    )""")
    op.execute("CREATE INDEX approvals_created_idx ON approvals (created_at DESC, approval_id)")
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON approvals FROM control_rw")
    op.execute("""CREATE TRIGGER approvals_immutable BEFORE UPDATE OR DELETE ON approvals
        FOR EACH ROW EXECUTE FUNCTION reject_mutation()""")
    op.execute("""CREATE TRIGGER approvals_no_truncate BEFORE TRUNCATE ON approvals
        FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation()""")

    op.execute("ALTER TABLE trace_steps DROP CONSTRAINT trace_steps_step_type_check")
    op.execute(
        f"ALTER TABLE trace_steps ADD CONSTRAINT trace_steps_step_type_check "
        f"CHECK (step_type IN ({STEP_TYPES}))"
    )


def downgrade():
    raise RuntimeError("Control migrations are append-only; restore into a new database.")
