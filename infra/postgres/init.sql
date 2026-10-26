\set ON_ERROR_STOP on
\getenv registry_password REGISTRY_PASSWORD
\getenv research_password RESEARCH_PASSWORD
\getenv eval_password EVAL_PASSWORD
\getenv feedback_password FEEDBACK_PASSWORD
CREATE ROLE registry_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'registry_password';
CREATE ROLE research_rw LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'research_password';
CREATE ROLE eval_rw LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'eval_password';
CREATE ROLE feedback_ro LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'feedback_password';
CREATE DATABASE registry_db;
CREATE DATABASE research_db;
CREATE DATABASE eval_db;
REVOKE ALL ON DATABASE registry_db, research_db, eval_db, postgres, template1 FROM PUBLIC;
GRANT CONNECT ON DATABASE registry_db TO registry_app;
GRANT CONNECT ON DATABASE research_db TO research_rw;
GRANT CONNECT ON DATABASE eval_db TO eval_rw, feedback_ro;

\connect registry_db
REVOKE ALL ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA registry;
REVOKE ALL ON SCHEMA registry FROM PUBLIC;
GRANT USAGE ON SCHEMA registry TO registry_app;
CREATE FUNCTION registry.reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'insert-only table: %', TG_TABLE_NAME USING ERRCODE = '55000'; END;
$$;
REVOKE ALL ON FUNCTION registry.reject_mutation() FROM PUBLIC;
CREATE TABLE registry.artifact_families (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON registry.artifact_families TO registry_app;
CREATE TRIGGER artifact_families_immutable BEFORE UPDATE OR DELETE ON registry.artifact_families
FOR EACH ROW EXECUTE FUNCTION registry.reject_mutation();
CREATE TRIGGER artifact_families_no_truncate BEFORE TRUNCATE ON registry.artifact_families
FOR EACH STATEMENT EXECUTE FUNCTION registry.reject_mutation();
CREATE TABLE registry.artifact_versions (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON registry.artifact_versions TO registry_app;
CREATE TRIGGER artifact_versions_immutable BEFORE UPDATE OR DELETE ON registry.artifact_versions
FOR EACH ROW EXECUTE FUNCTION registry.reject_mutation();
CREATE TRIGGER artifact_versions_no_truncate BEFORE TRUNCATE ON registry.artifact_versions
FOR EACH STATEMENT EXECUTE FUNCTION registry.reject_mutation();
CREATE TABLE registry.artifact_parents (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON registry.artifact_parents TO registry_app;
CREATE TRIGGER artifact_parents_immutable BEFORE UPDATE OR DELETE ON registry.artifact_parents
FOR EACH ROW EXECUTE FUNCTION registry.reject_mutation();
CREATE TRIGGER artifact_parents_no_truncate BEFORE TRUNCATE ON registry.artifact_parents
FOR EACH STATEMENT EXECUTE FUNCTION registry.reject_mutation();
CREATE TABLE registry.registry_events (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON registry.registry_events TO registry_app;
CREATE TRIGGER registry_events_immutable BEFORE UPDATE OR DELETE ON registry.registry_events
FOR EACH ROW EXECUTE FUNCTION registry.reject_mutation();
CREATE TRIGGER registry_events_no_truncate BEFORE TRUNCATE ON registry.registry_events
FOR EACH STATEMENT EXECUTE FUNCTION registry.reject_mutation();
ALTER TABLE registry.artifact_versions
ADD COLUMN artifact_version_id uuid NOT NULL UNIQUE,
ADD COLUMN content_hash text NOT NULL UNIQUE CHECK (content_hash ~ '^[0-9a-f]{64}$');

\connect research_db
REVOKE ALL ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA research;
REVOKE ALL ON SCHEMA research FROM PUBLIC;
GRANT USAGE ON SCHEMA research TO research_rw;
CREATE FUNCTION research.reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'insert-only table: %', TG_TABLE_NAME USING ERRCODE = '55000'; END;
$$;
REVOKE ALL ON FUNCTION research.reject_mutation() FROM PUBLIC;
CREATE TABLE research.programs (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.programs TO research_rw;
GRANT UPDATE, DELETE ON research.programs TO research_rw;
CREATE TABLE research.islands (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.islands TO research_rw;
GRANT UPDATE, DELETE ON research.islands TO research_rw;
CREATE TABLE research.generations (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.generations TO research_rw;
GRANT UPDATE, DELETE ON research.generations TO research_rw;
CREATE TABLE research.tasks (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.tasks TO research_rw;
GRANT UPDATE, DELETE ON research.tasks TO research_rw;
CREATE TABLE research.hypotheses (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.hypotheses TO research_rw;
GRANT UPDATE, DELETE ON research.hypotheses TO research_rw;
CREATE TABLE research.candidates (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.candidates TO research_rw;
GRANT UPDATE, DELETE ON research.candidates TO research_rw;
CREATE TABLE research.reviews (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.reviews TO research_rw;
GRANT UPDATE, DELETE ON research.reviews TO research_rw;
CREATE TABLE research.population_members (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.population_members TO research_rw;
GRANT UPDATE, DELETE ON research.population_members TO research_rw;
CREATE TABLE research.archive_cells (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.archive_cells TO research_rw;
GRANT UPDATE, DELETE ON research.archive_cells TO research_rw;
CREATE TABLE research.lineage_edges (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.lineage_edges TO research_rw;
GRANT UPDATE, DELETE ON research.lineage_edges TO research_rw;
CREATE TABLE research.report_cache (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.report_cache TO research_rw;
CREATE TRIGGER report_cache_immutable BEFORE UPDATE OR DELETE ON research.report_cache
FOR EACH ROW EXECUTE FUNCTION research.reject_mutation();
CREATE TRIGGER report_cache_no_truncate BEFORE TRUNCATE ON research.report_cache
FOR EACH STATEMENT EXECUTE FUNCTION research.reject_mutation();
CREATE TABLE research.report_links (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.report_links TO research_rw;
GRANT UPDATE, DELETE ON research.report_links TO research_rw;
CREATE TABLE research.feedback_cursor (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.feedback_cursor TO research_rw;
GRANT UPDATE, DELETE ON research.feedback_cursor TO research_rw;
CREATE TABLE research.interpretations (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.interpretations TO research_rw;
GRANT UPDATE, DELETE ON research.interpretations TO research_rw;
CREATE TABLE research.interpretation_challenges (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.interpretation_challenges TO research_rw;
GRANT UPDATE, DELETE ON research.interpretation_challenges TO research_rw;
CREATE TABLE research.knowledge_items (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.knowledge_items TO research_rw;
GRANT UPDATE, DELETE ON research.knowledge_items TO research_rw;
CREATE TABLE research.bandit_state (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.bandit_state TO research_rw;
GRANT UPDATE, DELETE ON research.bandit_state TO research_rw;
CREATE TABLE research.budget_ledger (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.budget_ledger TO research_rw;
CREATE TRIGGER budget_ledger_immutable BEFORE UPDATE OR DELETE ON research.budget_ledger
FOR EACH ROW EXECUTE FUNCTION research.reject_mutation();
CREATE TRIGGER budget_ledger_no_truncate BEFORE TRUNCATE ON research.budget_ledger
FOR EACH STATEMENT EXECUTE FUNCTION research.reject_mutation();
CREATE TABLE research.agent_runs (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.agent_runs TO research_rw;
GRANT UPDATE, DELETE ON research.agent_runs TO research_rw;
CREATE TABLE research.jobs (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.jobs TO research_rw;
GRANT UPDATE, DELETE ON research.jobs TO research_rw;
CREATE TABLE research.events (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.events TO research_rw;
CREATE TRIGGER events_immutable BEFORE UPDATE OR DELETE ON research.events
FOR EACH ROW EXECUTE FUNCTION research.reject_mutation();
CREATE TRIGGER events_no_truncate BEFORE TRUNCATE ON research.events
FOR EACH STATEMENT EXECUTE FUNCTION research.reject_mutation();
CREATE TABLE research.input_bundles (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.input_bundles TO research_rw;
CREATE TRIGGER input_bundles_immutable BEFORE UPDATE OR DELETE ON research.input_bundles
FOR EACH ROW EXECUTE FUNCTION research.reject_mutation();
CREATE TRIGGER input_bundles_no_truncate BEFORE TRUNCATE ON research.input_bundles
FOR EACH STATEMENT EXECUTE FUNCTION research.reject_mutation();
CREATE TABLE research.source_assets (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.source_assets TO research_rw;
CREATE TRIGGER source_assets_immutable BEFORE UPDATE OR DELETE ON research.source_assets
FOR EACH ROW EXECUTE FUNCTION research.reject_mutation();
CREATE TRIGGER source_assets_no_truncate BEFORE TRUNCATE ON research.source_assets
FOR EACH STATEMENT EXECUTE FUNCTION research.reject_mutation();
CREATE TABLE research.research_jobs (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.research_jobs TO research_rw;
GRANT UPDATE, DELETE ON research.research_jobs TO research_rw;
CREATE TABLE research.provider_profiles (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.provider_profiles TO research_rw;
CREATE TRIGGER provider_profiles_immutable BEFORE UPDATE OR DELETE ON research.provider_profiles
FOR EACH ROW EXECUTE FUNCTION research.reject_mutation();
CREATE TRIGGER provider_profiles_no_truncate BEFORE TRUNCATE ON research.provider_profiles
FOR EACH STATEMENT EXECUTE FUNCTION research.reject_mutation();
CREATE TABLE research.role_profiles (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.role_profiles TO research_rw;
CREATE TRIGGER role_profiles_immutable BEFORE UPDATE OR DELETE ON research.role_profiles
FOR EACH ROW EXECUTE FUNCTION research.reject_mutation();
CREATE TRIGGER role_profiles_no_truncate BEFORE TRUNCATE ON research.role_profiles
FOR EACH STATEMENT EXECUTE FUNCTION research.reject_mutation();
CREATE TABLE research.llm_attempts (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.llm_attempts TO research_rw;
GRANT UPDATE, DELETE ON research.llm_attempts TO research_rw;
CREATE TABLE research.delivery_refs (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON research.delivery_refs TO research_rw;
CREATE TRIGGER delivery_refs_immutable BEFORE UPDATE OR DELETE ON research.delivery_refs
FOR EACH ROW EXECUTE FUNCTION research.reject_mutation();
CREATE TRIGGER delivery_refs_no_truncate BEFORE TRUNCATE ON research.delivery_refs
FOR EACH STATEMENT EXECUTE FUNCTION research.reject_mutation();

\connect eval_db
REVOKE ALL ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA eval;
REVOKE ALL ON SCHEMA eval FROM PUBLIC;
GRANT USAGE ON SCHEMA eval TO eval_rw;
CREATE FUNCTION eval.reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'insert-only table: %', TG_TABLE_NAME USING ERRCODE = '55000'; END;
$$;
REVOKE ALL ON FUNCTION eval.reject_mutation() FROM PUBLIC;
CREATE TABLE eval.protocols (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.protocols TO eval_rw;
GRANT UPDATE, DELETE ON eval.protocols TO eval_rw;
CREATE TABLE eval.release_policies (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.release_policies TO eval_rw;
GRANT UPDATE, DELETE ON eval.release_policies TO eval_rw;
CREATE TABLE eval.epochs (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.epochs TO eval_rw;
GRANT UPDATE, DELETE ON eval.epochs TO eval_rw;
CREATE TABLE eval.data_snapshots (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.data_snapshots TO eval_rw;
GRANT UPDATE, DELETE ON eval.data_snapshots TO eval_rw;
CREATE TABLE eval.intake (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.intake TO eval_rw;
GRANT UPDATE, DELETE ON eval.intake TO eval_rw;
CREATE TABLE eval.intake_cursor (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.intake_cursor TO eval_rw;
GRANT UPDATE, DELETE ON eval.intake_cursor TO eval_rw;
CREATE TABLE eval.jobs (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.jobs TO eval_rw;
GRANT UPDATE, DELETE ON eval.jobs TO eval_rw;
CREATE TABLE eval.runs (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.runs TO eval_rw;
GRANT UPDATE, DELETE ON eval.runs TO eval_rw;
CREATE TABLE eval.metrics (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.metrics TO eval_rw;
GRANT UPDATE, DELETE ON eval.metrics TO eval_rw;
CREATE TABLE eval.series_files (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.series_files TO eval_rw;
GRANT UPDATE, DELETE ON eval.series_files TO eval_rw;
CREATE TABLE eval.official_records (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.official_records TO eval_rw;
CREATE TRIGGER official_records_immutable BEFORE UPDATE OR DELETE ON eval.official_records
FOR EACH ROW EXECUTE FUNCTION eval.reject_mutation();
CREATE TRIGGER official_records_no_truncate BEFORE TRUNCATE ON eval.official_records
FOR EACH STATEMENT EXECUTE FUNCTION eval.reject_mutation();
CREATE TABLE eval.trial_ledger (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.trial_ledger TO eval_rw;
CREATE TRIGGER trial_ledger_immutable BEFORE UPDATE OR DELETE ON eval.trial_ledger
FOR EACH ROW EXECUTE FUNCTION eval.reject_mutation();
CREATE TRIGGER trial_ledger_no_truncate BEFORE TRUNCATE ON eval.trial_ledger
FOR EACH STATEMENT EXECUTE FUNCTION eval.reject_mutation();
CREATE TABLE eval.fingerprints (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.fingerprints TO eval_rw;
GRANT UPDATE, DELETE ON eval.fingerprints TO eval_rw;
CREATE TABLE eval.trial_clusters (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.trial_clusters TO eval_rw;
GRANT UPDATE, DELETE ON eval.trial_clusters TO eval_rw;
CREATE TABLE eval.quota_usage (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.quota_usage TO eval_rw;
GRANT UPDATE, DELETE ON eval.quota_usage TO eval_rw;
CREATE TABLE eval.burn_meters (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.burn_meters TO eval_rw;
GRANT UPDATE, DELETE ON eval.burn_meters TO eval_rw;
CREATE TABLE eval.release_queue (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.release_queue TO eval_rw;
GRANT UPDATE, DELETE ON eval.release_queue TO eval_rw;
CREATE TABLE eval.released_reports (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.released_reports TO eval_rw;
CREATE TRIGGER released_reports_immutable BEFORE UPDATE OR DELETE ON eval.released_reports
FOR EACH ROW EXECUTE FUNCTION eval.reject_mutation();
CREATE TRIGGER released_reports_no_truncate BEFORE TRUNCATE ON eval.released_reports
FOR EACH STATEMENT EXECUTE FUNCTION eval.reject_mutation();
CREATE TABLE eval.ladder_state (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.ladder_state TO eval_rw;
GRANT UPDATE, DELETE ON eval.ladder_state TO eval_rw;
CREATE TABLE eval.sim_accounts (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.sim_accounts TO eval_rw;
GRANT UPDATE, DELETE ON eval.sim_accounts TO eval_rw;
CREATE TABLE eval.sim_orders (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.sim_orders TO eval_rw;
GRANT UPDATE, DELETE ON eval.sim_orders TO eval_rw;
CREATE TABLE eval.sim_fills (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.sim_fills TO eval_rw;
GRANT UPDATE, DELETE ON eval.sim_fills TO eval_rw;
CREATE TABLE eval.sim_positions (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.sim_positions TO eval_rw;
GRANT UPDATE, DELETE ON eval.sim_positions TO eval_rw;
CREATE TABLE eval.sim_nav (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.sim_nav TO eval_rw;
GRANT UPDATE, DELETE ON eval.sim_nav TO eval_rw;
CREATE TABLE eval.delivery_receipts (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.delivery_receipts TO eval_rw;
CREATE TRIGGER delivery_receipts_immutable BEFORE UPDATE OR DELETE ON eval.delivery_receipts
FOR EACH ROW EXECUTE FUNCTION eval.reject_mutation();
CREATE TRIGGER delivery_receipts_no_truncate BEFORE TRUNCATE ON eval.delivery_receipts
FOR EACH STATEMENT EXECUTE FUNCTION eval.reject_mutation();
CREATE TABLE eval.acceptance_cases (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.acceptance_cases TO eval_rw;
GRANT UPDATE, DELETE ON eval.acceptance_cases TO eval_rw;
CREATE TABLE eval.library (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.library TO eval_rw;
GRANT UPDATE, DELETE ON eval.library TO eval_rw;
CREATE TABLE eval.monitoring_alerts (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.monitoring_alerts TO eval_rw;
GRANT UPDATE, DELETE ON eval.monitoring_alerts TO eval_rw;
CREATE TABLE eval.events (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.events TO eval_rw;
CREATE TRIGGER events_immutable BEFORE UPDATE OR DELETE ON eval.events
FOR EACH ROW EXECUTE FUNCTION eval.reject_mutation();
CREATE TRIGGER events_no_truncate BEFORE TRUNCATE ON eval.events
FOR EACH STATEMENT EXECUTE FUNCTION eval.reject_mutation();
CREATE TABLE eval.public_policy_cards (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.public_policy_cards TO eval_rw;
CREATE TRIGGER public_policy_cards_immutable BEFORE UPDATE OR DELETE ON eval.public_policy_cards
FOR EACH ROW EXECUTE FUNCTION eval.reject_mutation();
CREATE TRIGGER public_policy_cards_no_truncate BEFORE TRUNCATE ON eval.public_policy_cards
FOR EACH STATEMENT EXECUTE FUNCTION eval.reject_mutation();
CREATE TABLE eval.public_protocol_cards (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON eval.public_protocol_cards TO eval_rw;
CREATE TRIGGER public_protocol_cards_immutable BEFORE UPDATE OR DELETE ON eval.public_protocol_cards
FOR EACH ROW EXECUTE FUNCTION eval.reject_mutation();
CREATE TRIGGER public_protocol_cards_no_truncate BEFORE TRUNCATE ON eval.public_protocol_cards
FOR EACH STATEMENT EXECUTE FUNCTION eval.reject_mutation();
ALTER TABLE eval.official_records
ADD COLUMN artifact_version_id uuid NOT NULL,
ADD COLUMN content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
ADD COLUMN protocol_version text NOT NULL,
ADD COLUMN dataset_version_id text NOT NULL,
ADD COLUMN evaluator_version text NOT NULL;
ALTER TABLE eval.released_reports
ADD COLUMN artifact_version_id uuid NOT NULL,
ADD COLUMN content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
ADD COLUMN protocol_version text NOT NULL,
ADD COLUMN dataset_version_id text NOT NULL,
ADD COLUMN evaluator_version text NOT NULL;
ALTER TABLE eval.trial_ledger ADD COLUMN official_record_id uuid NOT NULL
REFERENCES eval.official_records(id) DEFERRABLE INITIALLY DEFERRED;
CREATE SCHEMA feedback;
REVOKE ALL ON SCHEMA feedback FROM PUBLIC;
GRANT USAGE ON SCHEMA feedback TO feedback_ro;
CREATE VIEW feedback.released_reports_v WITH (security_barrier = true) AS
SELECT id, artifact_version_id, content_hash, protocol_version, dataset_version_id,
       evaluator_version, payload AS released_content, created_at FROM eval.released_reports;
CREATE VIEW feedback.artifact_status_v WITH (security_barrier = true) AS
SELECT id, artifact_version_id, payload->>'status' AS status, created_at FROM eval.released_reports;
CREATE VIEW feedback.library_v WITH (security_barrier = true) AS
SELECT id, payload->>'artifact_version_id' AS artifact_version_id,
       payload->>'membership' AS membership FROM eval.released_reports
WHERE payload->>'report_type' = 'library';
CREATE VIEW feedback.policy_card_v WITH (security_barrier = true) AS
SELECT id, payload FROM eval.public_policy_cards;
CREATE VIEW feedback.protocol_card_v WITH (security_barrier = true) AS
SELECT id, payload FROM eval.public_protocol_cards;
GRANT SELECT ON ALL TABLES IN SCHEMA feedback TO feedback_ro;
