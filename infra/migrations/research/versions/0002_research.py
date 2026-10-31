"""Phase 4 research_db (PLAN Section 16.2): jobs, the blackboard, the trace and the queue.

Insert-only tables (job events, the trace, agent runs, the budget ledger, reviews,
cached reports and their links, lineage edges, the candidate-version links, charter
versions, probe results and the audit log) have UPDATE, DELETE and TRUNCATE revoked
from research_rw and triggers that refuse them for every role. Deliverables are
immutable except for the time the front door first fetched them.

The population, archive and bandit tables are created here and filled by the
evolutionary engine in Phase 5.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

HEX64 = "'^[a-f0-9]{64}$'"
ISLAND = "CHECK (island_key ~ '^I[1-6]$')"
JOB_STATES = (
    "SUBMITTED",
    "VALIDATED",
    "RUNNING",
    "WAITING_FOR_EVALUATION",
    "DELIVERABLE_READY",
    "DELIVERED",
    "CLOSED",
)
CLOSE_DECISIONS = ("approved", "rejected", "expired", "cancelled", "budget_exhausted")
GENERATION_STATES = (
    "PENDING",
    "SYNCING",
    "PROPOSING",
    "PLANNING",
    "DEVELOPING",
    "SELECTING",
    "PUBLISHING",
    "CLOSED",
    "FAILED",
    "ABORTED",
)
TASK_TYPES = (
    "explore",
    "llm_mutation",
    "crossover",
    "repair",
    "syntactic_batch",
    "compose_strategy",
)
CANDIDATE_STATES = (
    "drafted",
    "invalid",
    "rejected",
    "approved",
    "selected",
    "not_selected",
    "published",
    "publish_failed",
)
INSERT_ONLY = (
    "job_events",
    "program_charters",
    "trace_steps",
    "agent_runs",
    "budget_ledger",
    "reviews",
    "report_cache",
    "report_links",
    "lineage_edges",
    "candidate_versions",
    "interpretation_challenges",
    "knowledge_items",
    "deliverable_items",
    "llm_probes",
    "events",
)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade():
    op.execute("CREATE SEQUENCE research_job_short_code_seq START 1")
    op.execute(f"""CREATE TABLE research_jobs (
        job_id uuid PRIMARY KEY,
        short_code text NOT NULL UNIQUE CHECK (short_code ~ '^J-[0-9]{{4,}}$'),
        submit_key text NOT NULL UNIQUE CHECK (submit_key ~ {HEX64}),
        brief jsonb NOT NULL,
        scan jsonb NOT NULL,
        state text NOT NULL CHECK (state IN ({_in(JOB_STATES)})),
        program_id uuid,
        parent_job_id uuid REFERENCES research_jobs (job_id),
        deliverable_criteria jsonb NOT NULL,
        budget jsonb NOT NULL,
        cost_cny numeric(18, 6) NOT NULL DEFAULT 0 CHECK (cost_cny >= 0),
        seed_version_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
        timeline jsonb NOT NULL,
        submitted_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        deadline_at timestamptz NOT NULL,
        next_generation_at timestamptz,
        daily_wait_until timestamptz,
        closed_at timestamptz,
        close_decision text CHECK (close_decision IN ({_in(CLOSE_DECISIONS)})),
        stop_reason text,
        approval_id uuid,
        principal text NOT NULL,
        request_id text NOT NULL,
        CHECK ((state = 'CLOSED') = (closed_at IS NOT NULL)),
        CHECK ((state = 'CLOSED') = (close_decision IS NOT NULL))
    )""")
    op.execute("CREATE INDEX research_jobs_state_idx ON research_jobs (state, submitted_at)")

    op.execute("""CREATE TABLE job_events (
        event_id uuid PRIMARY KEY,
        job_id uuid NOT NULL REFERENCES research_jobs (job_id),
        seq integer NOT NULL CHECK (seq > 0),
        at timestamptz NOT NULL,
        kind text NOT NULL,
        payload jsonb NOT NULL,
        request_id text NOT NULL,
        UNIQUE (job_id, seq)
    )""")

    op.execute("""CREATE TABLE programs (
        program_id uuid PRIMARY KEY,
        job_id uuid NOT NULL UNIQUE REFERENCES research_jobs (job_id),
        name text NOT NULL,
        status text NOT NULL CHECK (status IN ('active', 'paused', 'closed')),
        charter jsonb NOT NULL,
        charter_version integer NOT NULL CHECK (charter_version >= 1),
        research_snapshot_id text NOT NULL CHECK (research_snapshot_id ~ '^[a-f0-9]{64}$'),
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        created_by text NOT NULL
    )""")
    op.execute("""CREATE TABLE program_charters (
        program_id uuid NOT NULL REFERENCES programs (program_id),
        version integer NOT NULL CHECK (version >= 1),
        charter jsonb NOT NULL,
        sha256 text NOT NULL,
        reason text NOT NULL,
        created_at timestamptz NOT NULL,
        principal text NOT NULL,
        request_id text NOT NULL,
        PRIMARY KEY (program_id, version)
    )""")

    op.execute(f"""CREATE TABLE islands (
        island_id uuid PRIMARY KEY,
        program_id uuid NOT NULL REFERENCES programs (program_id),
        island_key text NOT NULL {ISLAND},
        theme text NOT NULL,
        guidance text,
        status text NOT NULL CHECK (status IN ('active', 'paused')),
        UNIQUE (program_id, island_key)
    )""")

    op.execute(f"""CREATE TABLE generations (
        generation_id uuid PRIMARY KEY,
        program_id uuid NOT NULL REFERENCES programs (program_id),
        seq integer NOT NULL CHECK (seq >= 0),
        state text NOT NULL CHECK (state IN ({_in(GENERATION_STATES)})),
        charter_version integer NOT NULL,
        proposal jsonb,
        plan jsonb,
        plan_source text CHECK (plan_source IN ('supervisor', 'repaired', 'fallback', 'seeds')),
        created_at timestamptz NOT NULL,
        started_at timestamptz,
        ended_at timestamptz,
        updated_at timestamptz NOT NULL,
        budget_stop text,
        cost_cny numeric(18, 6) NOT NULL DEFAULT 0 CHECK (cost_cny >= 0),
        summary jsonb,
        error_code text,
        UNIQUE (program_id, seq)
    )""")

    op.execute(f"""CREATE TABLE tasks (
        task_id uuid PRIMARY KEY,
        generation_id uuid NOT NULL REFERENCES generations (generation_id),
        ordinal integer NOT NULL CHECK (ordinal >= 0),
        type text NOT NULL CHECK (type IN ({_in(TASK_TYPES)})),
        island_key text NOT NULL {ISLAND},
        brief text NOT NULL,
        parent_version_ids jsonb NOT NULL,
        hypothesis_id uuid,
        max_candidates integer NOT NULL CHECK (max_candidates BETWEEN 1 AND 3),
        state text NOT NULL CHECK (state IN ('pending', 'running', 'done', 'failed', 'skipped')),
        attempts integer NOT NULL DEFAULT 0,
        error_code text,
        result jsonb,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        UNIQUE (generation_id, ordinal)
    )""")

    op.execute(f"""CREATE TABLE hypotheses (
        hypothesis_id uuid PRIMARY KEY,
        program_id uuid NOT NULL REFERENCES programs (program_id),
        island_key text NOT NULL {ISLAND},
        task_id uuid REFERENCES tasks (task_id),
        payload jsonb NOT NULL,
        status text NOT NULL CHECK (status IN ('open', 'supported', 'weakened', 'retired')),
        parent_hypothesis_id uuid,
        source text NOT NULL CHECK (source IN ('agent', 'seed')),
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL
    )""")

    op.execute(f"""CREATE TABLE candidates (
        candidate_id uuid PRIMARY KEY,
        program_id uuid NOT NULL REFERENCES programs (program_id),
        generation_id uuid NOT NULL REFERENCES generations (generation_id),
        task_id uuid NOT NULL REFERENCES tasks (task_id),
        hypothesis_id uuid REFERENCES hypotheses (hypothesis_id),
        island_key text NOT NULL {ISLAND},
        kind text NOT NULL CHECK (kind IN ('factor', 'strategy')),
        operator text NOT NULL,
        expression text,
        components jsonb,
        canonical_hash text CHECK (canonical_hash ~ {HEX64}),
        payload jsonb NOT NULL,
        analysis jsonb,
        workbench jsonb,
        similarity jsonb,
        prescreen jsonb,
        state text NOT NULL CHECK (state IN ({_in(CANDIDATE_STATES)})),
        reason text,
        review_rounds integer NOT NULL DEFAULT 0,
        provisional_fitness double precision,
        engineer_run_id uuid,
        parent_candidate_id uuid,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        CHECK ((kind = 'factor') = (expression IS NOT NULL))
    )""")
    op.execute("CREATE INDEX candidates_generation_idx ON candidates (generation_id, state)")
    op.execute("CREATE INDEX candidates_program_hash_idx ON candidates (program_id, canonical_hash)")
    op.execute("""CREATE TABLE candidate_versions (
        candidate_id uuid PRIMARY KEY REFERENCES candidates (candidate_id),
        version_id uuid NOT NULL UNIQUE,
        family_id uuid NOT NULL,
        content_hash text NOT NULL,
        published_at timestamptz NOT NULL,
        step_id uuid NOT NULL
    )""")

    op.execute("""CREATE TABLE reviews (
        review_id uuid PRIMARY KEY,
        candidate_id uuid NOT NULL REFERENCES candidates (candidate_id),
        round integer NOT NULL CHECK (round >= 1),
        verdict text NOT NULL CHECK (verdict IN ('approve', 'revise', 'reject')),
        payload jsonb NOT NULL,
        run_id uuid NOT NULL,
        provider text NOT NULL,
        created_at timestamptz NOT NULL,
        UNIQUE (candidate_id, round)
    )""")

    op.execute(f"""CREATE TABLE population_members (
        member_id uuid PRIMARY KEY,
        program_id uuid NOT NULL REFERENCES programs (program_id),
        island_key text NOT NULL {ISLAND},
        version_id uuid,
        candidate_id uuid,
        status text NOT NULL CHECK (status IN ('official', 'provisional', 'archived')),
        fitness double precision,
        descriptors jsonb,
        updated_at timestamptz NOT NULL
    )""")
    op.execute("""CREATE TABLE archive_cells (
        program_id uuid NOT NULL REFERENCES programs (program_id),
        cell_key text NOT NULL,
        elite_version_id uuid NOT NULL,
        fitness double precision NOT NULL,
        updated_at timestamptz NOT NULL,
        PRIMARY KEY (program_id, cell_key)
    )""")
    op.execute(f"""CREATE TABLE bandit_state (
        program_id uuid NOT NULL REFERENCES programs (program_id),
        island_key text NOT NULL {ISLAND},
        alpha double precision NOT NULL,
        beta double precision NOT NULL,
        updated_generation integer NOT NULL,
        PRIMARY KEY (program_id, island_key)
    )""")

    op.execute("""CREATE TABLE lineage_edges (
        child_version_id uuid NOT NULL,
        parent_version_id uuid NOT NULL,
        relation text NOT NULL,
        operator text NOT NULL,
        ast_diff jsonb,
        candidate_id uuid,
        program_id uuid,
        created_at timestamptz NOT NULL,
        PRIMARY KEY (child_version_id, parent_version_id)
    )""")

    op.execute(f"""CREATE TABLE report_cache (
        report_id uuid PRIMARY KEY,
        program_id uuid,
        version_id uuid NOT NULL,
        report_type text NOT NULL,
        released_at timestamptz NOT NULL,
        content jsonb NOT NULL,
        content_hash text NOT NULL CHECK (content_hash ~ {HEX64}),
        fetched_at timestamptz NOT NULL
    )""")
    op.execute("CREATE INDEX report_cache_version_idx ON report_cache (version_id, released_at)")
    op.execute("""CREATE TABLE report_links (
        link_id uuid PRIMARY KEY,
        report_id uuid NOT NULL REFERENCES report_cache (report_id),
        entity_type text NOT NULL CHECK (entity_type IN
            ('hypothesis', 'candidate', 'member', 'version', 'job', 'program')),
        entity_id uuid NOT NULL,
        created_at timestamptz NOT NULL,
        UNIQUE (report_id, entity_type, entity_id)
    )""")
    op.execute("""CREATE TABLE feedback_cursor (
        program_id uuid PRIMARY KEY REFERENCES programs (program_id),
        last_released_at timestamptz,
        last_report_id uuid,
        updated_at timestamptz NOT NULL
    )""")

    op.execute("""CREATE TABLE interpretations (
        interpretation_id uuid PRIMARY KEY,
        program_id uuid NOT NULL REFERENCES programs (program_id),
        generation_id uuid REFERENCES generations (generation_id),
        report_ids jsonb NOT NULL,
        version_id uuid,
        payload jsonb NOT NULL,
        final_payload jsonb,
        status text NOT NULL CHECK (status IN ('draft', 'final', 'amended')),
        run_id uuid NOT NULL,
        sampled_for_review boolean NOT NULL,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL
    )""")
    op.execute("""CREATE TABLE interpretation_challenges (
        challenge_id uuid PRIMARY KEY,
        interpretation_id uuid NOT NULL REFERENCES interpretations (interpretation_id),
        payload jsonb NOT NULL,
        verdict text NOT NULL CHECK (verdict IN ('accept', 'amend')),
        run_id uuid NOT NULL,
        created_at timestamptz NOT NULL
    )""")
    op.execute("""CREATE TABLE knowledge_items (
        item_id uuid PRIMARY KEY,
        program_id uuid NOT NULL REFERENCES programs (program_id),
        interpretation_id uuid REFERENCES interpretations (interpretation_id),
        kind text NOT NULL CHECK (kind IN ('failure_mode', 'insight', 'anti_pattern')),
        statement text NOT NULL,
        tags jsonb NOT NULL,
        evidence_report_ids jsonb NOT NULL,
        created_at timestamptz NOT NULL
    )""")

    op.execute("""CREATE TABLE budget_ledger (
        entry_id uuid PRIMARY KEY,
        at timestamptz NOT NULL,
        job_id uuid,
        program_id uuid,
        generation_id uuid,
        task_id uuid,
        run_id uuid,
        role text NOT NULL,
        provider text NOT NULL,
        model text NOT NULL,
        tokens_in bigint NOT NULL CHECK (tokens_in >= 0),
        tokens_out bigint NOT NULL CHECK (tokens_out >= 0),
        tokens_cached bigint NOT NULL CHECK (tokens_cached >= 0),
        price_period text NOT NULL CHECK (price_period IN ('peak', 'offpeak', 'flat')),
        cost_cny numeric(18, 6) NOT NULL CHECK (cost_cny >= 0)
    )""")
    op.execute("CREATE INDEX budget_ledger_job_idx ON budget_ledger (job_id, at)")
    op.execute("CREATE INDEX budget_ledger_at_idx ON budget_ledger (at)")

    op.execute(f"""CREATE TABLE agent_runs (
        run_id uuid PRIMARY KEY,
        step_id uuid,
        job_id uuid,
        program_id uuid,
        generation_id uuid,
        task_id uuid,
        candidate_id uuid,
        role text NOT NULL,
        provider text,
        model_id text NOT NULL,
        prompt_template_id text NOT NULL,
        prompt_sha256 text NOT NULL CHECK (prompt_sha256 ~ {HEX64}),
        request_messages jsonb NOT NULL,
        response_text text NOT NULL,
        response_json jsonb,
        usage jsonb NOT NULL,
        settings jsonb NOT NULL,
        status text NOT NULL CHECK (status IN ('ok', 'failed', 'fallback')),
        latency_ms double precision NOT NULL CHECK (latency_ms >= 0),
        created_at timestamptz NOT NULL
    )""")
    op.execute("CREATE INDEX agent_runs_task_idx ON agent_runs (task_id)")
    op.execute("CREATE INDEX agent_runs_candidate_idx ON agent_runs (candidate_id)")

    op.execute(f"""CREATE TABLE trace_steps (
        step_id uuid PRIMARY KEY,
        at timestamptz NOT NULL,
        job_id uuid,
        program_id uuid,
        generation_id uuid,
        task_id uuid,
        candidate_id uuid,
        version_id uuid,
        step_type text NOT NULL,
        actor_kind text NOT NULL
            CHECK (actor_kind IN ('owner', 'host_agent', 'llm', 'deterministic', 'evaluator')),
        actor text NOT NULL,
        provider text,
        model_id text,
        prompt_template_id text,
        prompt_sha256 text CHECK (prompt_sha256 ~ {HEX64}),
        run_id uuid,
        inputs jsonb NOT NULL,
        payload jsonb NOT NULL,
        outcome text NOT NULL CHECK (outcome IN ('ok', 'failed', 'retried', 'fallback')),
        request_id text NOT NULL
    )""")
    op.execute("CREATE INDEX trace_steps_candidate_idx ON trace_steps (candidate_id, at)")
    op.execute("CREATE INDEX trace_steps_version_idx ON trace_steps (version_id, at)")
    op.execute("CREATE INDEX trace_steps_job_idx ON trace_steps (job_id, at)")
    op.execute("CREATE INDEX trace_steps_task_idx ON trace_steps (task_id, at)")
    op.execute("CREATE INDEX trace_steps_run_idx ON trace_steps (run_id)")

    op.execute("""CREATE TABLE deliverables (
        deliverable_id uuid PRIMARY KEY,
        job_id uuid NOT NULL REFERENCES research_jobs (job_id),
        seq integer NOT NULL CHECK (seq >= 1),
        status text NOT NULL CHECK (status IN ('complete', 'best_effort')),
        summary text NOT NULL,
        costs jsonb NOT NULL,
        document jsonb NOT NULL,
        created_at timestamptz NOT NULL,
        fetched_at timestamptz,
        UNIQUE (job_id, seq)
    )""")
    op.execute("""CREATE FUNCTION guard_deliverable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP <> 'UPDATE' THEN RAISE EXCEPTION 'deliverables are never deleted'; END IF;
            IF (to_jsonb(NEW) - 'fetched_at') IS DISTINCT FROM (to_jsonb(OLD) - 'fetched_at')
               OR OLD.fetched_at IS NOT NULL OR NEW.fetched_at IS NULL THEN
                RAISE EXCEPTION 'a deliverable changes only by its first fetch time';
            END IF;
            RETURN NEW;
        END; $$""")
    op.execute("""CREATE TRIGGER deliverables_guard BEFORE UPDATE OR DELETE ON deliverables
        FOR EACH ROW EXECUTE FUNCTION guard_deliverable()""")
    op.execute("""CREATE TRIGGER deliverables_no_truncate BEFORE TRUNCATE ON deliverables
        FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation()""")
    op.execute("REVOKE DELETE, TRUNCATE ON deliverables FROM research_rw")
    op.execute(f"""CREATE TABLE deliverable_items (
        item_id uuid PRIMARY KEY,
        deliverable_id uuid NOT NULL REFERENCES deliverables (deliverable_id),
        ordinal integer NOT NULL CHECK (ordinal >= 1),
        version_id uuid NOT NULL,
        kind text NOT NULL CHECK (kind IN ('factor', 'strategy')),
        tier_reached text NOT NULL,
        iteration_history jsonb NOT NULL,
        trace_hash text NOT NULL CHECK (trace_hash ~ {HEX64}),
        short_code text NOT NULL,
        UNIQUE (deliverable_id, ordinal)
    )""")

    op.execute("""CREATE TABLE queue_jobs (
        queue_job_id uuid PRIMARY KEY,
        queue text NOT NULL,
        kind text NOT NULL,
        dedup_key text NOT NULL UNIQUE,
        payload jsonb NOT NULL,
        state text NOT NULL CHECK (state IN ('queued', 'running', 'done', 'failed')),
        run_after timestamptz NOT NULL,
        attempts integer NOT NULL DEFAULT 0,
        locked_by text,
        locked_at timestamptz,
        last_error text,
        created_at timestamptz NOT NULL,
        finished_at timestamptz
    )""")
    op.execute("CREATE INDEX queue_jobs_due_idx ON queue_jobs (queue, state, run_after)")

    op.execute("""CREATE TABLE research_control (
        id integer PRIMARY KEY CHECK (id = 1),
        paused boolean NOT NULL,
        updated_at timestamptz NOT NULL,
        principal text NOT NULL,
        reason text
    )""")

    op.execute("""CREATE TABLE llm_probes (
        probe_id uuid PRIMARY KEY,
        at timestamptz NOT NULL,
        trigger text NOT NULL CHECK (trigger IN ('setup', 'daily', 'job_start', 'manual')),
        ok boolean NOT NULL,
        report jsonb NOT NULL,
        request_id text NOT NULL
    )""")
    op.execute("CREATE INDEX llm_probes_at_idx ON llm_probes (at DESC)")

    op.execute("""CREATE TABLE events (
        event_id uuid PRIMARY KEY,
        at timestamptz NOT NULL,
        principal text NOT NULL,
        action text NOT NULL,
        entity_type text NOT NULL,
        entity_id text NOT NULL,
        request_id text NOT NULL,
        payload jsonb NOT NULL
    )""")
    op.execute("CREATE INDEX events_entity_idx ON events (entity_type, entity_id, at)")

    for table in INSERT_ONLY:
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM research_rw")
        op.execute(f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_mutation()""")
        op.execute(f"""CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation()""")


def downgrade():
    raise RuntimeError("Research migrations are append-only; restore into a new database.")
