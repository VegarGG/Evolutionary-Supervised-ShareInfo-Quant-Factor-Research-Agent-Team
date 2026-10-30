"""Phase 2 control_db: setup state and the front door's trace steps (PLAN 16.4, 14.3).

setup_state is insert-only; the latest row per step is current. trace_steps holds the
owner-side steps the front door writes for setup imports (DSL_VALIDATED and
SEEDS_PUBLISHED, the human_seed completeness rule of Section 14.5). Research-side
steps live in research_db; the trace export joins both by version and candidate id.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE setup_state (
        state_id uuid PRIMARY KEY,
        at timestamptz NOT NULL,
        step text NOT NULL CHECK (step IN ('pool', 'providers', 'data', 'token')),
        status text NOT NULL,
        details jsonb NOT NULL,
        principal text NOT NULL,
        request_id text NOT NULL
    )""")
    op.execute("CREATE INDEX setup_state_step_idx ON setup_state (step, at DESC, state_id DESC)")

    op.execute("""CREATE TABLE trace_steps (
        step_id uuid PRIMARY KEY,
        at timestamptz NOT NULL,
        job_id uuid,
        program_id uuid,
        generation_id uuid,
        task_id uuid,
        candidate_id uuid,
        version_id uuid,
        step_type text NOT NULL CHECK (step_type IN ('DSL_VALIDATED', 'SEEDS_PUBLISHED')),
        actor_kind text NOT NULL
            CHECK (actor_kind IN ('owner', 'host_agent', 'deterministic')),
        actor text NOT NULL,
        inputs jsonb NOT NULL,
        payload jsonb NOT NULL,
        outcome text NOT NULL CHECK (outcome IN ('ok', 'failed', 'retried', 'fallback')),
        request_id text NOT NULL
    )""")
    op.execute("CREATE INDEX trace_steps_candidate_idx ON trace_steps (candidate_id)")
    op.execute("CREATE INDEX trace_steps_version_idx ON trace_steps (version_id)")
    op.execute("CREATE INDEX trace_steps_job_idx ON trace_steps (job_id)")
    op.execute(
        "CREATE INDEX trace_steps_digest_idx ON trace_steps (step_type, (inputs->>'entry_digest'))"
    )

    for table in ("setup_state", "trace_steps"):
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM control_rw")
        op.execute(f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_mutation()""")
        op.execute(f"""CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation()""")


def downgrade():
    raise RuntimeError("Control migrations are append-only; restore into a new database.")
