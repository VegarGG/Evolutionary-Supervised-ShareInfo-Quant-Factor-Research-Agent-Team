"""Phase 8 eval_db (PLAN Section 9.5, P8.3): the optional Thresholdout mode for W2.

One state row per epoch holds the parameters pinned at the epoch's first W2 query, the
current noisy threshold and the remaining budget; it changes only forward (the budget
never grows, the draw counter never falls). Every Laplace draw and every query, with the
W0 and W2 values it compared, is logged insert-only for audit.
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

LOGS = ("thresholdout_draws", "thresholdout_queries")


def upgrade():
    op.execute("""CREATE TABLE eval.thresholdout_state (
        epoch_id text PRIMARY KEY REFERENCES eval.epochs (epoch_id),
        policy_ref text NOT NULL,
        threshold double precision NOT NULL CHECK (threshold > 0),
        sigma double precision NOT NULL CHECK (sigma > 0),
        budget_initial integer NOT NULL CHECK (budget_initial >= 1),
        seed bigint NOT NULL,
        noisy_threshold double precision NOT NULL,
        budget_remaining integer NOT NULL CHECK (budget_remaining BETWEEN 0 AND budget_initial),
        draws bigint NOT NULL CHECK (draws >= 0),
        queries bigint NOT NULL CHECK (queries >= 0),
        started_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL
    )""")
    op.execute("REVOKE DELETE, TRUNCATE ON eval.thresholdout_state FROM eval_rw")
    op.execute("""CREATE FUNCTION eval.guard_thresholdout_state() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP <> 'UPDATE' THEN RAISE EXCEPTION 'Thresholdout state is never deleted'; END IF;
            IF (NEW.epoch_id, NEW.policy_ref, NEW.threshold, NEW.sigma, NEW.budget_initial,
                NEW.seed, NEW.started_at)
               IS DISTINCT FROM (OLD.epoch_id, OLD.policy_ref, OLD.threshold, OLD.sigma,
                                 OLD.budget_initial, OLD.seed, OLD.started_at) THEN
                RAISE EXCEPTION 'Thresholdout parameters are pinned for the epoch';
            END IF;
            IF NEW.budget_remaining > OLD.budget_remaining OR NEW.draws < OLD.draws
               OR NEW.queries < OLD.queries THEN
                RAISE EXCEPTION 'the Thresholdout budget and draws only move forward';
            END IF;
            RETURN NEW;
        END; $$""")
    op.execute("""CREATE TRIGGER thresholdout_state_guard
        BEFORE UPDATE OR DELETE ON eval.thresholdout_state
        FOR EACH ROW EXECUTE FUNCTION eval.guard_thresholdout_state()""")

    op.execute("""CREATE TABLE eval.thresholdout_draws (
        epoch_id text NOT NULL REFERENCES eval.epochs (epoch_id),
        seq bigint NOT NULL CHECK (seq >= 1),
        purpose text NOT NULL CHECK (purpose IN ('threshold', 'query', 'answer')),
        scale double precision NOT NULL CHECK (scale > 0),
        value double precision NOT NULL,
        record_id uuid NOT NULL REFERENCES eval.official_records (record_id),
        version_id uuid NOT NULL,
        at timestamptz NOT NULL,
        PRIMARY KEY (epoch_id, seq)
    )""")
    op.execute("""CREATE TABLE eval.thresholdout_queries (
        record_id uuid PRIMARY KEY REFERENCES eval.official_records (record_id),
        epoch_id text NOT NULL REFERENCES eval.epochs (epoch_id),
        version_id uuid NOT NULL,
        w0_value double precision,
        w2_value double precision,
        noisy_threshold double precision NOT NULL,
        query_noise double precision,
        over_threshold boolean NOT NULL,
        answer double precision,
        source text NOT NULL CHECK (source IN ('w0', 'w2', 'exhausted', 'missing')),
        budget_after integer NOT NULL CHECK (budget_after >= 0),
        at timestamptz NOT NULL,
        CHECK ((answer IS NULL) = (source IN ('exhausted', 'missing')))
    )""")
    for table in LOGS:
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON eval.{table} FROM eval_rw")
        op.execute(f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON eval.{table}
            FOR EACH ROW EXECUTE FUNCTION reject_mutation()""")
        op.execute(f"""CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON eval.{table}
            FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation()""")


def downgrade():
    raise RuntimeError("Evaluation migrations are append-only; restore into a new database.")
