-- All DDL is applied by the migration owner, never by an application role.
ALTER TABLE eval.protocols
  ADD COLUMN protocol_id text NOT NULL,
  ADD COLUMN version text NOT NULL,
  ADD COLUMN yaml text NOT NULL,
  ADD COLUMN sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  ADD COLUMN status text NOT NULL CHECK (status IN ('draft','active','retired')),
  ADD CONSTRAINT protocol_revision UNIQUE (protocol_id, version);
CREATE FUNCTION eval.protect_protocol() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status <> 'draft' THEN
    RAISE EXCEPTION 'activated protocol is immutable' USING ERRCODE='55000';
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION eval.protect_protocol() FROM PUBLIC;
CREATE TRIGGER protocols_frozen BEFORE UPDATE OR DELETE ON eval.protocols
  FOR EACH ROW EXECUTE FUNCTION eval.protect_protocol();
CREATE TRIGGER protocols_no_truncate BEFORE TRUNCATE ON eval.protocols
  FOR EACH STATEMENT EXECUTE FUNCTION eval.reject_mutation();

ALTER TABLE eval.jobs
  ADD COLUMN queue text NOT NULL DEFAULT 'evaluation',
  ADD COLUMN state text NOT NULL DEFAULT 'queued'
    CHECK (state IN ('queued','running','complete','failed')),
  ADD COLUMN run_after timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  ADD COLUMN fence bigint NOT NULL DEFAULT 0 CHECK (fence >= 0),
  ADD COLUMN locked_by text,
  ADD COLUMN lease_until timestamptz,
  ADD CONSTRAINT job_lease CHECK ((state = 'running') =
    (locked_by IS NOT NULL AND lease_until IS NOT NULL));
CREATE INDEX jobs_ready ON eval.jobs (queue, run_after, created_at, id)
  WHERE state IN ('queued','running');
REVOKE DELETE ON eval.jobs FROM eval_rw;

-- Typed immutable run evidence. Baseline reservations may contain old fixture rows;
-- NOT VALID retains them, but all new rows must satisfy these constraints.
ALTER TABLE eval.runs ADD COLUMN official_record_id uuid
  REFERENCES eval.official_records(id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE eval.metrics ADD COLUMN run_id uuid
  REFERENCES eval.runs(id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE eval.series_files ADD COLUMN run_id uuid
  REFERENCES eval.runs(id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE eval.trial_ledger ADD CONSTRAINT one_trial_per_record UNIQUE (official_record_id);
ALTER TABLE eval.official_records ADD COLUMN trial_id uuid;
ALTER TABLE eval.official_records ADD CONSTRAINT record_trial
  FOREIGN KEY (trial_id) REFERENCES eval.trial_ledger(id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE eval.official_records ADD CONSTRAINT record_requires_trial
  CHECK (trial_id IS NOT NULL) NOT VALID;
CREATE FUNCTION eval.check_trial_pair() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM eval.trial_ledger t
      WHERE t.id=NEW.trial_id AND t.official_record_id=NEW.id) THEN
    RAISE EXCEPTION 'official record requires its paired trial' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION eval.check_trial_pair() FROM PUBLIC;
CREATE CONSTRAINT TRIGGER official_record_trial_pair AFTER INSERT ON eval.official_records
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION eval.check_trial_pair();

-- Replay series, fingerprints and cluster snapshots cannot be revised in place.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['runs','metrics','series_files','fingerprints','trial_clusters',
    'data_snapshots','epochs'] LOOP
    EXECUTE format('REVOKE UPDATE, DELETE ON eval.%I FROM eval_rw', t);
    EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON eval.%I '
      'FOR EACH ROW EXECUTE FUNCTION eval.reject_mutation()', t || '_immutable', t);
    EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON eval.%I '
      'FOR EACH STATEMENT EXECUTE FUNCTION eval.reject_mutation()', t || '_no_truncate', t);
  END LOOP;
END;
$$;

-- Audit metadata only: private payloads are not copied into exception messages.
CREATE FUNCTION eval.audit_write() RETURNS trigger LANGUAGE plpgsql
  SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE rowdata jsonb;
BEGIN
  rowdata := CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
  IF coalesce(rowdata->>'created_by','')='' OR rowdata->>'request_id' IS NULL THEN
    RAISE EXCEPTION 'write requires principal and request id' USING ERRCODE='23514';
  END IF;
  INSERT INTO eval.events(id,payload,created_by,request_id)
    VALUES(gen_random_uuid(),jsonb_build_object('action',TG_OP,'entity_type',TG_TABLE_NAME,
      'entity_id',rowdata->>'id'), rowdata->>'created_by',(rowdata->>'request_id')::uuid);
  RETURN COALESCE(NEW,OLD);
END;
$$;
REVOKE ALL ON FUNCTION eval.audit_write() FROM PUBLIC;
DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='eval'
      AND tablename NOT IN ('events','alembic_version') LOOP
    EXECUTE format('CREATE TRIGGER %I AFTER INSERT OR UPDATE OR DELETE ON eval.%I '
      'FOR EACH ROW EXECUTE FUNCTION eval.audit_write()', t || '_audit', t);
  END LOOP;
END;
$$;

-- A connection without an authorized program selection sees no private reports.
-- Stage 4 must bind these IDs after authenticating the feedback principal.
CREATE OR REPLACE VIEW feedback.released_reports_v WITH (security_barrier=true) AS
 SELECT id,artifact_version_id,content_hash,protocol_version,dataset_version_id,
 evaluator_version,payload AS released_content,created_at FROM eval.released_reports
 WHERE payload->>'program_id'=ANY(string_to_array(
   coalesce(current_setting('qfr.program_ids',true),''),','));
CREATE OR REPLACE VIEW feedback.artifact_status_v WITH (security_barrier=true) AS
 SELECT DISTINCT ON (artifact_version_id) id,artifact_version_id,
 payload->>'status' AS status,created_at FROM eval.released_reports
 WHERE payload->>'program_id'=ANY(string_to_array(
   coalesce(current_setting('qfr.program_ids',true),''),','))
 ORDER BY artifact_version_id,created_at DESC,id DESC;
CREATE OR REPLACE VIEW feedback.library_v WITH (security_barrier=true) AS
 SELECT id,payload->>'artifact_version_id' AS artifact_version_id,
 payload->>'membership' AS membership FROM eval.released_reports
 WHERE payload->>'report_type'='library' AND payload->>'program_id'=ANY(string_to_array(
   coalesce(current_setting('qfr.program_ids',true),''),','));
