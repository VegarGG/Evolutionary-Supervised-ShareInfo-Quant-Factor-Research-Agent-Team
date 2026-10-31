"""Phase 6 eval_db (PLAN Sections 8.7, 8.8, 9.2, 10 and 16.3): W2, the holdout, the
Ladder, trial clusters, simulation, acceptance cases and alerts.

The lifecycle gains the states after W1 (Section 7.9). Runs and official records gain
the W2, holdout and simulation stages; the release queue gains the w2, advancement, sim
and decision reports. Strategies are no longer held at intake, so rows held by Phase 3
return to Discovered and are evaluated like any version.

What happened is insert-only, as in Phase 3: Ladder events, trial clusters and their
runs, simulation orders, fills, positions, NAV, forward RankIC and events. The rows
that carry a current state (the Ladder's family best, a simulation account, an
acceptance case, an alert) change only in the ways their triggers allow. An acceptance
case can be opened only for a completed incubation (ACC-02) and closes only with an
approval id, never as accepted when a gate failed (ACC-03).
"""

from alembic import op

revision = "0003"
down_revision = "0002"
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
)
JOB_KINDS = ("fingerprint", "evaluate", "w2", "holdout")
STAGES = ("screening", "w1", "w2", "holdout", "simulation")
REPORT_TYPES = (
    "intake",
    "screening",
    "w1",
    "w2",
    "advancement",
    "sim",
    "decision",
    "library",
)
GATES = ("G-W1", "G-W2", "G-HOLDOUT", "G-DSR", "G-PBO", "G-HLZ", "G-FWD", "G-NOVELTY", "G-OPS")
SIM_EVENTS = (
    "STARTED",
    "CHECKPOINT",
    "DATA_REVISION",
    "INCOMPLETE_DAY",
    "PAUSED",
    "RESUMED",
    "COMPLETED",
    "FAILED",
    "STOPPED",
)
INSERT_ONLY = (
    "ladder_events",
    "trial_cluster_runs",
    "trial_clusters",
    "sim_orders",
    "sim_fills",
    "sim_positions",
    "sim_nav",
    "sim_rankic",
    "sim_events",
)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _check(table: str, name: str, condition: str) -> None:
    op.execute(f"ALTER TABLE eval.{table} DROP CONSTRAINT {name}")
    op.execute(f"ALTER TABLE eval.{table} ADD CONSTRAINT {name} CHECK ({condition})")


def upgrade():
    # The lifecycle after W1 (Section 7.9) and the stages and reports it produces.
    _check("intake", "intake_state_check", f"state IN ({_in(INTAKE_STATES)})")
    _check("queue_jobs", "queue_jobs_kind_check", f"kind IN ({_in(JOB_KINDS)})")
    _check("runs", "runs_stage_check", f"stage IN ({_in(STAGES)})")
    _check("official_records", "official_records_stage_check", f"stage IN ({_in(STAGES)})")
    _check("release_queue", "release_queue_report_type_check", f"report_type IN ({_in(REPORT_TYPES)})")
    _check(
        "released_reports",
        "released_reports_report_type_check",
        f"report_type IN ({_in(REPORT_TYPES)})",
    )
    op.execute("""ALTER TABLE eval.intake
        ADD COLUMN w2_queued_at timestamptz,
        ADD COLUMN w2_admitted_at timestamptz,
        ADD COLUMN w2_passed boolean,
        ADD COLUMN holdout_admitted_at timestamptz,
        ADD COLUMN holdout_passed boolean""")
    # Strategies were held until their plugin existed (Phase 3 decision 8).
    op.execute(
        "UPDATE eval.intake SET state = 'Discovered', hold_reason = NULL WHERE state = 'Held'"
    )

    # The Ladder (Section 9.2): the family best at full precision, private to the
    # evaluator, and every comparison it made.
    op.execute("""CREATE TABLE eval.ladder_state (
        epoch_id text NOT NULL REFERENCES eval.epochs (epoch_id),
        family_id uuid NOT NULL,
        best_value double precision NOT NULL,
        released_best double precision NOT NULL,
        record_id uuid NOT NULL REFERENCES eval.official_records (record_id),
        updated_at timestamptz NOT NULL,
        PRIMARY KEY (epoch_id, family_id)
    )""")
    op.execute("REVOKE DELETE, TRUNCATE ON eval.ladder_state FROM eval_rw")
    op.execute("""CREATE TABLE eval.ladder_events (
        event_id uuid PRIMARY KEY,
        epoch_id text NOT NULL REFERENCES eval.epochs (epoch_id),
        family_id uuid NOT NULL,
        record_id uuid NOT NULL UNIQUE REFERENCES eval.official_records (record_id),
        version_id uuid NOT NULL,
        value double precision,
        previous_best double precision NOT NULL,
        eta double precision NOT NULL,
        improved boolean NOT NULL,
        released_best double precision,
        at timestamptz NOT NULL,
        CHECK (improved = (released_best IS NOT NULL))
    )""")

    # Nightly behavioral clusters of the trial ledger, for N_eff (Section 8.7).
    op.execute("""CREATE TABLE eval.trial_cluster_runs (
        run_id uuid PRIMARY KEY,
        epoch_id text NOT NULL REFERENCES eval.epochs (epoch_id),
        window_name text NOT NULL CHECK (window_name IN ('W1', 'W2', 'W3')),
        computed_at timestamptz NOT NULL,
        method text NOT NULL CHECK (method IN ('single_linkage', 'families')),
        similarity double precision NOT NULL,
        trials integer NOT NULL CHECK (trials >= 0),
        families integer NOT NULL CHECK (families >= 0),
        clusters integer NOT NULL CHECK (clusters >= 0),
        n_eff integer NOT NULL CHECK (n_eff >= 0),
        without_fingerprint integer NOT NULL CHECK (without_fingerprint >= 0),
        request_id text NOT NULL
    )""")
    op.execute(
        "CREATE INDEX trial_cluster_runs_idx ON eval.trial_cluster_runs "
        "(epoch_id, window_name, computed_at DESC)"
    )
    op.execute("""CREATE TABLE eval.trial_clusters (
        run_id uuid NOT NULL REFERENCES eval.trial_cluster_runs (run_id),
        epoch_id text NOT NULL REFERENCES eval.epochs (epoch_id),
        window_name text NOT NULL CHECK (window_name IN ('W1', 'W2', 'W3')),
        version_id uuid NOT NULL,
        cluster_id integer NOT NULL CHECK (cluster_id >= 0),
        computed_at timestamptz NOT NULL,
        PRIMARY KEY (run_id, version_id)
    )""")

    # Simulated trading (Section 10.2). An account carries the current state of one
    # simulation; everything it did is in the insert-only tables below.
    op.execute("""CREATE TABLE eval.sim_accounts (
        sim_id uuid PRIMARY KEY,
        version_id uuid NOT NULL,
        kind text NOT NULL CHECK (kind IN ('factor', 'strategy')),
        purpose text NOT NULL CHECK (purpose IN ('incubation', 'monitoring')),
        mode text NOT NULL CHECK (mode IN ('forward', 'replay')),
        epoch_id text NOT NULL REFERENCES eval.epochs (epoch_id),
        protocol_ref text NOT NULL,
        settings jsonb NOT NULL,
        capital double precision NOT NULL CHECK (capital > 0),
        not_before date NOT NULL,
        start_date date,
        last_day date,
        days_done integer NOT NULL DEFAULT 0 CHECK (days_done >= 0),
        required_days integer CHECK (required_days > 0),
        cash double precision,
        status text NOT NULL
            CHECK (status IN ('waiting', 'running', 'paused', 'completed', 'failed', 'stopped')),
        error_code text,
        entry_id uuid,
        created_at timestamptz NOT NULL,
        started_at timestamptz,
        updated_at timestamptz NOT NULL,
        finished_at timestamptz,
        request_id text NOT NULL,
        CHECK ((purpose = 'incubation') = (required_days IS NOT NULL)),
        CHECK ((status IN ('completed', 'failed', 'stopped')) = (finished_at IS NOT NULL))
    )""")
    op.execute(
        "CREATE UNIQUE INDEX sim_accounts_live_idx ON eval.sim_accounts (version_id, purpose) "
        "WHERE status IN ('waiting', 'running', 'paused')"
    )
    op.execute("CREATE INDEX sim_accounts_status_idx ON eval.sim_accounts (status, created_at)")
    op.execute("REVOKE DELETE, TRUNCATE ON eval.sim_accounts FROM eval_rw")
    op.execute("""CREATE FUNCTION eval.guard_sim_account() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP <> 'UPDATE' THEN RAISE EXCEPTION 'simulations are never deleted'; END IF;
            IF (to_jsonb(NEW) - ARRAY['start_date', 'last_day', 'days_done', 'cash', 'status',
                                      'error_code', 'started_at', 'updated_at', 'finished_at'])
               IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['start_date', 'last_day', 'days_done', 'cash', 'status',
                                      'error_code', 'started_at', 'updated_at', 'finished_at']) THEN
                RAISE EXCEPTION 'a simulation''s version, mode and settings are immutable';
            END IF;
            IF OLD.status IN ('completed', 'failed', 'stopped') THEN
                RAISE EXCEPTION 'a finished simulation is immutable';
            END IF;
            IF NEW.days_done < OLD.days_done THEN
                RAISE EXCEPTION 'simulation days never go back';
            END IF;
            RETURN NEW;
        END; $$""")
    op.execute("""CREATE TRIGGER sim_accounts_guard BEFORE UPDATE OR DELETE ON eval.sim_accounts
        FOR EACH ROW EXECUTE FUNCTION eval.guard_sim_account()""")
    op.execute("""CREATE TRIGGER sim_accounts_no_truncate BEFORE TRUNCATE ON eval.sim_accounts
        FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation()""")
    op.execute("""CREATE TABLE eval.sim_orders (
        sim_id uuid NOT NULL REFERENCES eval.sim_accounts (sim_id),
        decided_on date NOT NULL,
        seq integer NOT NULL CHECK (seq >= 0),
        instrument text NOT NULL,
        side text NOT NULL CHECK (side IN ('buy', 'sell')),
        reason text NOT NULL CHECK (reason IN ('entry', 'dropout', 'pending')),
        score double precision,
        PRIMARY KEY (sim_id, decided_on, seq)
    )""")
    op.execute("""CREATE TABLE eval.sim_fills (
        sim_id uuid NOT NULL REFERENCES eval.sim_accounts (sim_id),
        day date NOT NULL,
        seq integer NOT NULL CHECK (seq >= 0),
        decided_on date NOT NULL,
        instrument text NOT NULL,
        side text NOT NULL CHECK (side IN ('buy', 'sell')),
        status text NOT NULL CHECK (status IN ('filled', 'blocked', 'skipped')),
        reason text,
        shares bigint NOT NULL CHECK (shares >= 0),
        price double precision,
        value double precision NOT NULL,
        cost double precision NOT NULL,
        PRIMARY KEY (sim_id, day, seq)
    )""")
    op.execute("""CREATE TABLE eval.sim_positions (
        sim_id uuid NOT NULL REFERENCES eval.sim_accounts (sim_id),
        day date NOT NULL,
        instrument text NOT NULL,
        shares bigint NOT NULL CHECK (shares > 0),
        price double precision NOT NULL,
        value double precision NOT NULL,
        adjustment double precision NOT NULL,
        PRIMARY KEY (sim_id, day, instrument)
    )""")
    op.execute("""CREATE TABLE eval.sim_nav (
        sim_id uuid NOT NULL REFERENCES eval.sim_accounts (sim_id),
        day date NOT NULL,
        day_number integer NOT NULL CHECK (day_number >= 1),
        nav double precision NOT NULL,
        cash double precision NOT NULL,
        gross_return double precision,
        net_return double precision,
        turnover double precision,
        costs double precision NOT NULL,
        holdings integer NOT NULL CHECK (holdings >= 0),
        benchmark_return double precision,
        complete boolean NOT NULL,
        snapshot_id text NOT NULL,
        PRIMARY KEY (sim_id, day),
        UNIQUE (sim_id, day_number)
    )""")
    op.execute("""CREATE TABLE eval.sim_rankic (
        sim_id uuid NOT NULL REFERENCES eval.sim_accounts (sim_id),
        decision_day date NOT NULL,
        computed_on date NOT NULL,
        value double precision,
        PRIMARY KEY (sim_id, decision_day)
    )""")
    op.execute(f"""CREATE TABLE eval.sim_events (
        event_id uuid PRIMARY KEY,
        sim_id uuid NOT NULL REFERENCES eval.sim_accounts (sim_id),
        at timestamptz NOT NULL,
        day date,
        kind text NOT NULL CHECK (kind IN ({_in(SIM_EVENTS)})),
        payload jsonb NOT NULL,
        request_id text NOT NULL
    )""")
    op.execute("CREATE INDEX sim_events_sim_idx ON eval.sim_events (sim_id, at)")

    # Acceptance cases (Section 10.3). The case number is the short code the owner repeats.
    op.execute("CREATE SEQUENCE eval.acceptance_case_seq")
    op.execute(f"""CREATE TABLE eval.acceptance_cases (
        case_id uuid PRIMARY KEY,
        short_code text NOT NULL UNIQUE CHECK (short_code ~ '^C-[0-9]{{4,}}$'),
        version_id uuid NOT NULL,
        epoch_id text NOT NULL REFERENCES eval.epochs (epoch_id),
        sim_id uuid NOT NULL UNIQUE REFERENCES eval.sim_accounts (sim_id),
        kind text NOT NULL CHECK (kind IN ('factor', 'strategy')),
        mode text NOT NULL CHECK (mode IN ('forward', 'replay')),
        gate_results jsonb NOT NULL,
        recommendation text NOT NULL CHECK (recommendation IN ('ACCEPT', 'REJECT')),
        failing_gates text[] NOT NULL,
        state text NOT NULL CHECK (state IN ('open', 'decided')),
        decision text CHECK (decision IN ('accepted', 'rejected')),
        reason text CHECK (reason IN ('gate_failed', 'owner_rejected', 'incubation_failed',
                                      'gates_passed')),
        reason_gate text CHECK (reason_gate IN ({_in(GATES)})),
        rationale text CHECK (length(rationale) BETWEEN 1 AND 4000),
        approval_id uuid,
        decided_by text,
        decided_at timestamptz,
        opened_at timestamptz NOT NULL,
        request_id text NOT NULL,
        UNIQUE (version_id, epoch_id),
        CHECK ((recommendation = 'ACCEPT') = (cardinality(failing_gates) = 0)),
        CHECK ((state = 'decided') = (decision IS NOT NULL)),
        CHECK (state = 'open' OR (approval_id IS NOT NULL AND rationale IS NOT NULL
                                  AND decided_at IS NOT NULL AND decided_by IS NOT NULL
                                  AND reason IS NOT NULL)),
        CHECK (decision IS DISTINCT FROM 'accepted' OR recommendation = 'ACCEPT')
    )""")
    op.execute("REVOKE DELETE, TRUNCATE ON eval.acceptance_cases FROM eval_rw")
    op.execute("""CREATE FUNCTION eval.guard_acceptance_case() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE sim eval.sim_accounts%ROWTYPE;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                SELECT * INTO sim FROM eval.sim_accounts WHERE sim_id = NEW.sim_id;
                IF sim.purpose IS DISTINCT FROM 'incubation'
                   OR sim.version_id IS DISTINCT FROM NEW.version_id
                   OR sim.status NOT IN ('completed', 'failed')
                   OR (sim.status = 'completed' AND sim.days_done < sim.required_days) THEN
                    RAISE EXCEPTION 'an acceptance case opens only after incubation ends';
                END IF;
                IF NEW.state <> 'open' THEN
                    RAISE EXCEPTION 'an acceptance case opens undecided';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP <> 'UPDATE' THEN RAISE EXCEPTION 'acceptance cases are never deleted'; END IF;
            IF OLD.state <> 'open' OR NEW.state <> 'decided' THEN
                RAISE EXCEPTION 'an acceptance case is decided once';
            END IF;
            IF (to_jsonb(NEW) - ARRAY['state', 'decision', 'reason', 'reason_gate', 'rationale',
                                      'approval_id', 'decided_by', 'decided_at'])
               IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['state', 'decision', 'reason', 'reason_gate', 'rationale',
                                      'approval_id', 'decided_by', 'decided_at']) THEN
                RAISE EXCEPTION 'an acceptance case''s gates are immutable';
            END IF;
            RETURN NEW;
        END; $$""")
    op.execute("""CREATE TRIGGER acceptance_cases_guard
        BEFORE INSERT OR UPDATE OR DELETE ON eval.acceptance_cases
        FOR EACH ROW EXECUTE FUNCTION eval.guard_acceptance_case()""")
    op.execute("""CREATE TRIGGER acceptance_cases_no_truncate BEFORE TRUNCATE ON eval.acceptance_cases
        FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation()""")

    # Alerts (Sections 9.4 and 10.4): one per condition, readable in qfr.ops.alerts.
    op.execute("""CREATE TABLE eval.alerts (
        alert_id uuid PRIMARY KEY,
        kind text NOT NULL CHECK (kind IN ('decay', 'staleness', 'burn', 'ops')),
        dedup_key text NOT NULL UNIQUE,
        version_id uuid,
        sim_id uuid REFERENCES eval.sim_accounts (sim_id),
        at timestamptz NOT NULL,
        details jsonb NOT NULL,
        state text NOT NULL CHECK (state IN ('open', 'acknowledged')),
        acknowledged_by text,
        acknowledged_at timestamptz,
        request_id text NOT NULL,
        CHECK ((state = 'acknowledged') = (acknowledged_at IS NOT NULL))
    )""")
    op.execute("CREATE INDEX alerts_state_idx ON eval.alerts (state, at)")
    op.execute("REVOKE DELETE, TRUNCATE ON eval.alerts FROM eval_rw")
    op.execute("""CREATE FUNCTION eval.guard_alert() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP <> 'UPDATE' THEN RAISE EXCEPTION 'alerts are never deleted'; END IF;
            IF OLD.state <> 'open' OR NEW.state <> 'acknowledged'
               OR (to_jsonb(NEW) - ARRAY['state', 'acknowledged_by', 'acknowledged_at'])
                  IS DISTINCT FROM
                  (to_jsonb(OLD) - ARRAY['state', 'acknowledged_by', 'acknowledged_at']) THEN
                RAISE EXCEPTION 'an alert can only be acknowledged';
            END IF;
            RETURN NEW;
        END; $$""")
    op.execute("""CREATE TRIGGER alerts_guard BEFORE UPDATE OR DELETE ON eval.alerts
        FOR EACH ROW EXECUTE FUNCTION eval.guard_alert()""")
    op.execute("""CREATE TRIGGER alerts_no_truncate BEFORE TRUNCATE ON eval.alerts
        FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation()""")

    for table in INSERT_ONLY:
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON eval.{table} FROM eval_rw")
        op.execute(f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON eval.{table}
            FOR EACH ROW EXECUTE FUNCTION reject_mutation()""")
        op.execute(f"""CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON eval.{table}
            FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation()""")

    # The released timeline now has W2, advancement, simulation and decision reports.
    op.execute("""CREATE OR REPLACE VIEW feedback.artifact_status_v AS
        SELECT DISTINCT ON (version_id)
               version_id, family_id, program_id, report_id, release_seq, report_type,
               content ->> 'status' AS status, released_at
        FROM eval.released_reports
        WHERE released_at <= now() AND report_type <> 'library'
        ORDER BY version_id, release_seq DESC""")


def downgrade():
    raise RuntimeError("Evaluation migrations are append-only; restore into a new database.")
