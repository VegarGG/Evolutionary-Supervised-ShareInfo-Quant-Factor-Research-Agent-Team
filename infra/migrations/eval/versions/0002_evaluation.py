"""Phase 3 eval_db (PLAN Section 16.3): intake, library, queue, runs, records, release.

Two schemas. `eval` is private to the evaluator and the owner (through eval-admin-api).
`feedback` holds only the five views granted to feedback_ro (Section 16.6).

Insert-only tables (official records, the trial ledger, released reports, metrics,
series files, runs, fingerprints, snapshots, quota usage, public cards and the audit
log) have UPDATE, DELETE and TRUNCATE revoked from eval_rw, and triggers that refuse
them for every role, including the migration owner. Configuration versions and epochs
are immutable once active: a trigger allows only the status transitions draft -> active
and active -> retired, and never a change of content.

Simulation, acceptance, alerts, the Ladder and trial clusters arrive with Phase 6.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

HEX64 = "'^[a-f0-9]{64}$'"
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
)
REASON_CODES = (
    "SCHEMA_INVALID",
    "KIND_UNSUPPORTED",
    "PARSE_ERROR",
    "TYPE_ERROR",
    "COMPLEXITY_LIMIT",
    "FORBIDDEN_CONSTRUCT",
    "DECLARATION_MISMATCH",
    "COMPONENT_INVALID",
    "DUPLICATE_OF",
    "NEAR_DUPLICATE_OF",
    "QUOTA_DEFERRED",
    "QUOTA_EXPIRED",
    "LOW_COVERAGE",
    "LOOKAHEAD_DETECTED",
    "RUNTIME_LIMIT",
    "DEGENERATE",
    "INTERNAL_ERROR",
)
CONFIG_TABLES = ("protocols", "release_policies", "quotas")
INSERT_ONLY = (
    "data_snapshots",
    "public_cards",
    "fingerprints",
    "quota_usage",
    "runs",
    "metrics",
    "series_files",
    "official_records",
    "trial_ledger",
    "released_reports",
    "events",
)
FEEDBACK_VIEWS = (
    "released_reports_v",
    "artifact_status_v",
    "library_v",
    "policy_card_v",
    "protocol_card_v",
)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade():
    op.execute("""CREATE FUNCTION eval.guard_versioned_config() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP <> 'UPDATE' THEN
                RAISE EXCEPTION 'configuration versions are never deleted';
            END IF;
            IF (to_jsonb(NEW) - ARRAY['status', 'activated_at', 'activated_by', 'approval_id',
                                      'retired_at'])
               IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['status', 'activated_at', 'activated_by', 'approval_id',
                                      'retired_at']) THEN
                RAISE EXCEPTION 'configuration content is immutable';
            END IF;
            IF OLD.status = 'draft' AND NEW.status = 'active'
               AND OLD.activated_at IS NULL AND NEW.activated_at IS NOT NULL
               AND NEW.activated_by IS NOT NULL AND NEW.retired_at IS NULL THEN
                RETURN NEW;
            END IF;
            IF OLD.status = 'active' AND NEW.status = 'retired' AND NEW.retired_at IS NOT NULL
               AND NEW.activated_at = OLD.activated_at AND NEW.activated_by = OLD.activated_by
               AND NEW.approval_id IS NOT DISTINCT FROM OLD.approval_id THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'invalid configuration status change % -> %', OLD.status, NEW.status;
        END; $$""")

    # Protocols, release policies and quotas: one table each, identical shape.
    for table in CONFIG_TABLES:
        op.execute(f"""CREATE TABLE eval.{table} (
            id text NOT NULL CHECK (id ~ '^[a-z0-9][a-z0-9_-]*$'),
            version text NOT NULL CHECK (version ~ '^[A-Za-z0-9._-]{{1,32}}$'),
            yaml text NOT NULL,
            config jsonb NOT NULL,
            sha256 text NOT NULL CHECK (sha256 ~ {HEX64}),
            status text NOT NULL CHECK (status IN ('draft', 'active', 'retired')),
            created_at timestamptz NOT NULL,
            created_by text NOT NULL,
            activated_at timestamptz,
            activated_by text,
            approval_id uuid,
            retired_at timestamptz,
            request_id text NOT NULL,
            PRIMARY KEY (id, version),
            CHECK ((status = 'draft') = (activated_at IS NULL)),
            CHECK ((status = 'retired') = (retired_at IS NOT NULL))
        )""")
        op.execute(
            f"CREATE UNIQUE INDEX {table}_one_active ON eval.{table} ((true)) "
            "WHERE status = 'active'"
        )
        op.execute(f"""CREATE TRIGGER {table}_guard BEFORE UPDATE OR DELETE ON eval.{table}
            FOR EACH ROW EXECUTE FUNCTION eval.guard_versioned_config()""")
        op.execute(f"""CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON eval.{table}
            FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation()""")
        op.execute(f"REVOKE DELETE, TRUNCATE ON eval.{table} FROM eval_rw")

    # Epochs: window dates live here, resolved and pinned at activation (Section 6.4).
    op.execute(f"""CREATE TABLE eval.epochs (
        epoch_id text PRIMARY KEY,
        version text NOT NULL,
        config jsonb NOT NULL,
        source_sha256 text NOT NULL CHECK (source_sha256 ~ {HEX64}),
        snapshot_id text NOT NULL CHECK (snapshot_id ~ {HEX64}),
        embargo_check jsonb NOT NULL,
        status text NOT NULL CHECK (status IN ('active', 'retired')),
        started_at timestamptz NOT NULL,
        activated_at timestamptz NOT NULL,
        activated_by text NOT NULL,
        approval_id uuid,
        retired_at timestamptz,
        request_id text NOT NULL,
        CHECK ((status = 'retired') = (retired_at IS NOT NULL))
    )""")
    op.execute(
        "CREATE UNIQUE INDEX epochs_one_active ON eval.epochs ((true)) WHERE status = 'active'"
    )
    op.execute("""CREATE FUNCTION eval.guard_epoch() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP <> 'UPDATE' THEN RAISE EXCEPTION 'epochs are never deleted'; END IF;
            IF (to_jsonb(NEW) - ARRAY['status', 'retired_at'])
               IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status', 'retired_at']) THEN
                RAISE EXCEPTION 'epoch windows are immutable once active';
            END IF;
            IF OLD.status = 'active' AND NEW.status = 'retired' THEN RETURN NEW; END IF;
            RAISE EXCEPTION 'invalid epoch status change % -> %', OLD.status, NEW.status;
        END; $$""")
    op.execute("""CREATE TRIGGER epochs_guard BEFORE UPDATE OR DELETE ON eval.epochs
        FOR EACH ROW EXECUTE FUNCTION eval.guard_epoch()""")
    op.execute("""CREATE TRIGGER epochs_no_truncate BEFORE TRUNCATE ON eval.epochs
        FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation()""")
    op.execute("REVOKE DELETE, TRUNCATE ON eval.epochs FROM eval_rw")

    op.execute(f"""CREATE TABLE eval.data_snapshots (
        snapshot_id text PRIMARY KEY CHECK (snapshot_id ~ {HEX64}),
        zone text NOT NULL CHECK (zone IN ('full', 'research')),
        manifest jsonb NOT NULL,
        first_date date NOT NULL,
        last_date date NOT NULL,
        created_at timestamptz NOT NULL,
        registered_by text NOT NULL,
        request_id text NOT NULL
    )""")

    # The public cards derived from each protocol and policy version (Section 8.2, 9.6).
    op.execute(f"""CREATE TABLE eval.public_cards (
        kind text NOT NULL CHECK (kind IN ('protocol', 'policy', 'quotas')),
        id text NOT NULL,
        version text NOT NULL,
        ref text NOT NULL,
        sha256 text NOT NULL CHECK (sha256 ~ {HEX64}),
        content jsonb NOT NULL,
        created_at timestamptz NOT NULL,
        PRIMARY KEY (kind, id, version)
    )""")

    # Intake (Section 8.3): one row per pulled version. The state column follows the
    # evaluation lifecycle (Section 7.9) and is owned by the evaluator.
    op.execute(f"""CREATE TABLE eval.intake (
        version_id uuid PRIMARY KEY,
        published_seq bigint NOT NULL UNIQUE,
        content_hash text NOT NULL CHECK (content_hash ~ {HEX64}),
        canonical_hash text NOT NULL CHECK (canonical_hash ~ {HEX64}),
        family_id uuid NOT NULL,
        program_id uuid,
        job_id uuid,
        kind text NOT NULL,
        manifest jsonb NOT NULL,
        discovered_at timestamptz NOT NULL,
        state text NOT NULL CHECK (state IN ({_in(INTAKE_STATES)})),
        reason_code text CHECK (reason_code IN ({_in(REASON_CODES)})),
        duplicate_of uuid,
        similarity double precision,
        hold_reason text,
        fingerprint_error text,
        w1_passed boolean,
        deferred_at timestamptz,
        enqueued_at timestamptz,
        decided_at timestamptz,
        updated_at timestamptz NOT NULL,
        request_id text NOT NULL
    )""")
    op.execute("CREATE INDEX intake_state_idx ON eval.intake (state, published_seq)")
    op.execute("CREATE INDEX intake_canonical_idx ON eval.intake (canonical_hash, published_seq)")
    op.execute("CREATE INDEX intake_family_idx ON eval.intake (family_id, published_seq)")
    op.execute("""CREATE TABLE eval.intake_cursor (
        id smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
        last_published_seq bigint NOT NULL CHECK (last_published_seq >= 0),
        updated_at timestamptz NOT NULL
    )""")

    # The evaluator's view of the pools (Section 10.4), pulled by event sequence.
    op.execute("""CREATE TABLE eval.pool_sync_cursor (
        pool text PRIMARY KEY CHECK (pool IN ('factor', 'strategy')),
        last_event_seq bigint NOT NULL CHECK (last_event_seq >= 0),
        updated_at timestamptz NOT NULL
    )""")
    op.execute("""CREATE TABLE eval.library (
        version_id uuid PRIMARY KEY,
        pool text NOT NULL CHECK (pool IN ('factor', 'strategy')),
        entry_id uuid NOT NULL,
        status text NOT NULL CHECK (status IN ('seed', 'active', 'retired')),
        approved_tier text CHECK (approved_tier IN ('w1_pass', 'w2_pass', 'advanced', 'incubated')),
        effective_from timestamptz,
        last_event_seq bigint NOT NULL,
        updated_at timestamptz NOT NULL
    )""")

    # The evaluation queue (Section 16.3, D6): FOR UPDATE SKIP LOCKED.
    op.execute("CREATE SEQUENCE eval.queue_priority_seq")
    op.execute("""CREATE TABLE eval.queue_jobs (
        queue_job_id uuid PRIMARY KEY,
        queue text NOT NULL,
        kind text NOT NULL CHECK (kind IN ('fingerprint', 'evaluate')),
        version_id uuid NOT NULL,
        payload jsonb NOT NULL,
        priority bigint NOT NULL,
        state text NOT NULL CHECK (state IN ('queued', 'running', 'done', 'failed')),
        run_after timestamptz NOT NULL,
        attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
        locked_by text,
        locked_at timestamptz,
        last_error text,
        created_at timestamptz NOT NULL,
        finished_at timestamptz,
        UNIQUE (kind, version_id)
    )""")
    op.execute(
        "CREATE INDEX queue_jobs_claim_idx ON eval.queue_jobs (queue, state, priority) "
        "WHERE state = 'queued'"
    )

    op.execute(f"""CREATE TABLE eval.fingerprints (
        version_id uuid NOT NULL,
        epoch_id text NOT NULL REFERENCES eval.epochs (epoch_id),
        snapshot_id text NOT NULL REFERENCES eval.data_snapshots (snapshot_id),
        uri text NOT NULL,
        sha256 text NOT NULL CHECK (sha256 ~ {HEX64}),
        dates_sha256 text NOT NULL CHECK (dates_sha256 ~ {HEX64}),
        created_at timestamptz NOT NULL,
        PRIMARY KEY (version_id, epoch_id)
    )""")

    # Quota consumption ledger (Section 9.3); usage is counted over rolling windows.
    op.execute("""CREATE TABLE eval.quota_usage (
        usage_id uuid PRIMARY KEY,
        scope text NOT NULL CHECK (scope IN ('family', 'program', 'global')),
        key text NOT NULL,
        window_name text NOT NULL CHECK (window_name IN ('W1', 'W2', 'W3')),
        version_id uuid NOT NULL,
        used_at timestamptz NOT NULL,
        quota_ref text NOT NULL
    )""")
    op.execute(
        "CREATE INDEX quota_usage_idx ON eval.quota_usage (scope, key, window_name, used_at)"
    )

    op.execute(f"""CREATE TABLE eval.runs (
        run_id uuid PRIMARY KEY,
        version_id uuid NOT NULL,
        stage text NOT NULL CHECK (stage IN ('screening', 'w1')),
        window_name text NOT NULL CHECK (window_name IN ('W1', 'W2', 'W3', 'W4')),
        protocol_ref text NOT NULL,
        epoch_id text NOT NULL REFERENCES eval.epochs (epoch_id),
        snapshot_id text NOT NULL REFERENCES eval.data_snapshots (snapshot_id),
        code_version text NOT NULL,
        image_digest text NOT NULL,
        seed bigint NOT NULL,
        status text NOT NULL CHECK (status IN ('succeeded', 'failed')),
        started_at timestamptz NOT NULL,
        finished_at timestamptz NOT NULL,
        error_code text CHECK (error_code IN ({_in(REASON_CODES)})),
        resources jsonb NOT NULL,
        request_id text NOT NULL,
        content_hash text NOT NULL CHECK (content_hash ~ {HEX64})
    )""")
    op.execute("CREATE INDEX runs_version_idx ON eval.runs (version_id)")
    op.execute("""CREATE TABLE eval.metrics (
        run_id uuid NOT NULL REFERENCES eval.runs (run_id),
        name text NOT NULL,
        horizon integer,
        value double precision,
        UNIQUE NULLS NOT DISTINCT (run_id, name, horizon)
    )""")
    op.execute(f"""CREATE TABLE eval.series_files (
        run_id uuid NOT NULL REFERENCES eval.runs (run_id),
        kind text NOT NULL CHECK (kind IN ('rankic', 'ls_returns', 'nav', 'factor_values')),
        uri text NOT NULL,
        sha256 text NOT NULL CHECK (sha256 ~ {HEX64}),
        bytes bigint NOT NULL,
        PRIMARY KEY (run_id, kind)
    )""")

    # Exactly one immutable official record per stage, window and epoch (Section 8.9).
    op.execute(f"""CREATE TABLE eval.official_records (
        record_id uuid PRIMARY KEY,
        version_id uuid NOT NULL,
        content_hash text NOT NULL CHECK (content_hash ~ {HEX64}),
        family_id uuid NOT NULL,
        program_id uuid,
        job_id uuid,
        stage text NOT NULL CHECK (stage IN ('screening', 'w1')),
        window_name text NOT NULL CHECK (window_name IN ('W1', 'W2', 'W3', 'W4')),
        run_ids uuid[] NOT NULL CHECK (cardinality(run_ids) >= 1),
        protocol_id text NOT NULL,
        protocol_version text NOT NULL,
        epoch_id text NOT NULL REFERENCES eval.epochs (epoch_id),
        snapshot_id text NOT NULL REFERENCES eval.data_snapshots (snapshot_id),
        code_version text NOT NULL CHECK (length(code_version) > 0),
        image_digest text NOT NULL CHECK (length(image_digest) > 0),
        seed bigint NOT NULL,
        summary jsonb NOT NULL,
        metrics jsonb NOT NULL,
        results_hash text NOT NULL CHECK (results_hash ~ {HEX64}),
        created_at timestamptz NOT NULL,
        principal text NOT NULL,
        request_id text NOT NULL,
        UNIQUE (version_id, stage, window_name, epoch_id)
    )""")

    # Every evaluated version counts (INV-7), written in the record's transaction.
    op.execute("""CREATE TABLE eval.trial_ledger (
        window_name text NOT NULL CHECK (window_name IN ('W1', 'W2', 'W3')),
        epoch_id text NOT NULL REFERENCES eval.epochs (epoch_id),
        version_id uuid NOT NULL,
        family_id uuid NOT NULL,
        program_id uuid,
        job_id uuid,
        record_id uuid NOT NULL REFERENCES eval.official_records (record_id),
        sharpe_daily double precision,
        n_obs integer NOT NULL CHECK (n_obs >= 0),
        skew double precision,
        kurt_raw double precision,
        fingerprint_ref text,
        counted_at timestamptz NOT NULL,
        PRIMARY KEY (epoch_id, window_name, version_id)
    )""")

    op.execute("""CREATE TABLE eval.burn_meters (
        epoch_id text NOT NULL REFERENCES eval.epochs (epoch_id),
        window_name text NOT NULL CHECK (window_name IN ('W1', 'W2', 'W3')),
        trials integer NOT NULL CHECK (trials >= 0),
        released_values integer NOT NULL CHECK (released_values >= 0),
        queries_used integer NOT NULL CHECK (queries_used >= 0),
        budget integer,
        status text NOT NULL CHECK (status IN ('green', 'amber', 'red')),
        updated_at timestamptz NOT NULL,
        PRIMARY KEY (epoch_id, window_name)
    )""")

    # Release (Section 9.2): queued at record time, released at the batch time.
    op.execute("""CREATE TABLE eval.release_queue (
        queue_id uuid PRIMARY KEY,
        report_type text NOT NULL
            CHECK (report_type IN ('intake', 'screening', 'w1', 'library')),
        version_id uuid NOT NULL,
        record_id uuid REFERENCES eval.official_records (record_id),
        payload jsonb NOT NULL,
        due_at timestamptz NOT NULL,
        state text NOT NULL CHECK (state IN ('queued', 'released')),
        created_at timestamptz NOT NULL,
        released_report_id uuid,
        request_id text NOT NULL,
        CHECK ((state = 'released') = (released_report_id IS NOT NULL))
    )""")
    op.execute(
        "CREATE INDEX release_queue_due_idx ON eval.release_queue (due_at, created_at) "
        "WHERE state = 'queued'"
    )
    op.execute(f"""CREATE TABLE eval.released_reports (
        report_id uuid PRIMARY KEY,
        release_seq bigserial UNIQUE,
        queue_id uuid NOT NULL UNIQUE REFERENCES eval.release_queue (queue_id),
        version_id uuid NOT NULL,
        content_hash text NOT NULL CHECK (content_hash ~ {HEX64}),
        family_id uuid NOT NULL,
        program_id uuid,
        report_type text NOT NULL
            CHECK (report_type IN ('intake', 'screening', 'w1', 'library')),
        policy_ref text NOT NULL,
        protocol_card_ref text NOT NULL,
        protocol_id text NOT NULL,
        protocol_version text NOT NULL,
        snapshot_id text NOT NULL CHECK (snapshot_id ~ {HEX64}),
        code_version text NOT NULL CHECK (length(code_version) > 0),
        content jsonb NOT NULL,
        report jsonb NOT NULL,
        released_at timestamptz NOT NULL
    )""")
    op.execute(
        "CREATE INDEX released_reports_version_idx "
        "ON eval.released_reports (version_id, release_seq)"
    )

    op.execute("""CREATE TABLE eval.events (
        event_id uuid PRIMARY KEY,
        at timestamptz NOT NULL,
        principal text NOT NULL,
        action text NOT NULL,
        entity_type text NOT NULL,
        entity_id text NOT NULL,
        request_id text NOT NULL,
        payload jsonb NOT NULL
    )""")
    op.execute("CREATE INDEX events_entity_idx ON eval.events (entity_type, entity_id, at)")
    op.execute("CREATE INDEX events_request_idx ON eval.events (request_id)")

    for table in INSERT_ONLY:
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON eval.{table} FROM eval_rw")
        op.execute(f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON eval.{table}
            FOR EACH ROW EXECUTE FUNCTION reject_mutation()""")
        op.execute(f"""CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON eval.{table}
            FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation()""")

    # The feedback schema: released content only. Views run with their owner's rights, so
    # feedback_ro needs SELECT on these five views and nothing in the eval schema.
    op.execute("""CREATE VIEW feedback.released_reports_v AS
        SELECT report_id, release_seq, version_id, family_id, program_id, report_type,
               report, released_at
        FROM eval.released_reports
        WHERE released_at <= now()""")
    op.execute("""CREATE VIEW feedback.artifact_status_v AS
        SELECT DISTINCT ON (version_id)
               version_id, family_id, program_id, report_id, release_seq, report_type,
               content ->> 'status' AS status, released_at
        FROM eval.released_reports
        WHERE released_at <= now() AND report_type IN ('intake', 'screening', 'w1')
        ORDER BY version_id, release_seq DESC""")
    op.execute("""CREATE VIEW feedback.library_v AS
        SELECT version_id, pool, status FROM eval.library""")
    # The policy card names the quotas it is released under (Section 9.6), so its view
    # carries the active policy card and the active quota card.
    op.execute("""CREATE VIEW feedback.protocol_card_v AS
        SELECT c.kind, c.ref, c.sha256, c.content, t.activated_at
        FROM eval.public_cards c
        JOIN eval.protocols t ON t.id = c.id AND t.version = c.version
        WHERE c.kind = 'protocol' AND t.status = 'active'""")
    op.execute("""CREATE VIEW feedback.policy_card_v AS
        SELECT c.kind, c.ref, c.sha256, c.content, t.activated_at
        FROM eval.public_cards c
        JOIN eval.release_policies t ON t.id = c.id AND t.version = c.version
        WHERE c.kind = 'policy' AND t.status = 'active'
        UNION ALL
        SELECT c.kind, c.ref, c.sha256, c.content, q.activated_at
        FROM eval.public_cards c
        JOIN eval.quotas q ON q.id = c.id AND q.version = c.version
        WHERE c.kind = 'quotas' AND q.status = 'active'""")
    # eval_rw may read the same views: it already reads the underlying tables, and the
    # evaluator's in-process tests read released content exactly as feedback-api does.
    op.execute("GRANT USAGE ON SCHEMA feedback TO eval_rw")
    for view in FEEDBACK_VIEWS:
        op.execute(f"REVOKE ALL ON feedback.{view} FROM PUBLIC")
        op.execute(f"GRANT SELECT ON feedback.{view} TO feedback_ro, eval_rw")


def downgrade():
    raise RuntimeError("Evaluation migrations are append-only; restore into a new database.")
