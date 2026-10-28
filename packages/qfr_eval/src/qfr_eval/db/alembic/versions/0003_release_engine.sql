ALTER TABLE eval.release_policies ADD COLUMN policy_id text, ADD COLUMN version integer,
 ADD COLUMN sha256 text UNIQUE, ADD COLUMN status text NOT NULL DEFAULT 'draft'
 CHECK(status IN ('draft','active','retired')),
 ADD CONSTRAINT release_policy_identity UNIQUE(policy_id,version),
 ADD CONSTRAINT release_policy_metadata CHECK(policy_id IS NOT NULL AND length(policy_id)>0
   AND version IS NOT NULL AND version>0 AND sha256 IS NOT NULL
   AND sha256 ~ '^[0-9a-f]{64}$') NOT VALID;
CREATE TRIGGER release_policy_frozen BEFORE UPDATE OR DELETE ON eval.release_policies
 FOR EACH ROW EXECUTE FUNCTION eval.protect_protocol();
CREATE TRIGGER release_policy_no_truncate BEFORE TRUNCATE ON eval.release_policies
 FOR EACH STATEMENT EXECUTE FUNCTION eval.reject_mutation();

ALTER TABLE eval.quota_usage ADD COLUMN subject_sha256 text,
 ADD COLUMN policy_sha256 text REFERENCES eval.release_policies(sha256),
 ADD COLUMN artifact_version_id uuid, ADD COLUMN program_id text, ADD COLUMN family_id text,
 ADD COLUMN epoch_id text, ADD COLUMN stage text CHECK(stage IN ('w1','w2')),
 ADD COLUMN admitted_at timestamptz,
 ADD CONSTRAINT quota_version UNIQUE(program_id,epoch_id,stage,artifact_version_id),
 ADD CONSTRAINT quota_metadata CHECK(subject_sha256 IS NOT NULL
   AND subject_sha256 ~ '^[0-9a-f]{64}$' AND policy_sha256 IS NOT NULL
   AND artifact_version_id IS NOT NULL AND program_id IS NOT NULL AND length(program_id)>0
   AND family_id IS NOT NULL AND length(family_id)>0 AND epoch_id IS NOT NULL
   AND length(epoch_id)>0 AND stage IS NOT NULL AND admitted_at IS NOT NULL) NOT VALID;
CREATE INDEX quota_family_time ON eval.quota_usage(program_id,family_id,stage,admitted_at);
CREATE INDEX quota_program_time ON eval.quota_usage(program_id,stage,admitted_at);
CREATE INDEX quota_global_time ON eval.quota_usage(stage,admitted_at);
CREATE INDEX quota_epoch ON eval.quota_usage(epoch_id,stage);
REVOKE UPDATE,DELETE ON eval.quota_usage FROM eval_rw;
CREATE TRIGGER quota_usage_immutable BEFORE UPDATE OR DELETE ON eval.quota_usage
 FOR EACH ROW EXECUTE FUNCTION eval.reject_mutation();
CREATE TRIGGER quota_usage_no_truncate BEFORE TRUNCATE ON eval.quota_usage
 FOR EACH STATEMENT EXECUTE FUNCTION eval.reject_mutation();

CREATE TABLE eval.quota_requests (
 id uuid PRIMARY KEY,payload jsonb NOT NULL,created_by text NOT NULL,request_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),subject_sha256 text NOT NULL UNIQUE,
 policy_sha256 text NOT NULL REFERENCES eval.release_policies(sha256),
 first_seen_at timestamptz NOT NULL,
 state text NOT NULL CHECK(state IN ('deferred','admitted','expired')),
 next_eligible_at timestamptz,admission_id uuid REFERENCES eval.quota_usage(id),
 CHECK((state='admitted')=(admission_id IS NOT NULL)),
 CHECK(state='deferred' OR next_eligible_at IS NULL)
);
GRANT SELECT,INSERT,UPDATE ON eval.quota_requests TO eval_rw;
CREATE FUNCTION eval.protect_quota_request() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (NEW.id,NEW.payload,NEW.subject_sha256,NEW.policy_sha256,NEW.first_seen_at,NEW.created_at)
    IS DISTINCT FROM (OLD.id,OLD.payload,OLD.subject_sha256,OLD.policy_sha256,OLD.first_seen_at,OLD.created_at)
    OR OLD.state<>'deferred' THEN
   RAISE EXCEPTION 'quota request binding or terminal result is immutable' USING ERRCODE='55000';
 END IF;
 RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION eval.protect_quota_request() FROM PUBLIC;
CREATE TRIGGER quota_request_binding BEFORE UPDATE ON eval.quota_requests
 FOR EACH ROW EXECUTE FUNCTION eval.protect_quota_request();
CREATE TRIGGER quota_requests_audit AFTER INSERT OR UPDATE ON eval.quota_requests
 FOR EACH ROW EXECUTE FUNCTION eval.audit_write();
CREATE TRIGGER quota_requests_no_truncate BEFORE TRUNCATE ON eval.quota_requests
 FOR EACH STATEMENT EXECUTE FUNCTION eval.reject_mutation();

ALTER TABLE eval.release_queue
 ADD COLUMN source_kind text CHECK(source_kind IN ('official_record','intake_transition')),
 ADD COLUMN source_id uuid,
 ADD COLUMN official_record_id uuid REFERENCES eval.official_records(id),
 ADD COLUMN intake_transition_id uuid REFERENCES eval.intake_transitions(id),
 ADD COLUMN source_sha256 text,
 ADD COLUMN policy_sha256 text REFERENCES eval.release_policies(sha256),
 ADD COLUMN program_id text,ADD COLUMN family_id text,ADD COLUMN epoch_id text,
 ADD COLUMN eligible_at timestamptz,
 ADD COLUMN state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','published')),
 ADD COLUMN published_report_id uuid REFERENCES eval.released_reports(id),
 ADD CONSTRAINT release_source_unique UNIQUE(source_kind,source_id,policy_sha256),
 ADD CONSTRAINT release_queue_metadata CHECK(source_id IS NOT NULL AND source_kind IS NOT NULL
   AND source_sha256 IS NOT NULL AND source_sha256 ~ '^[0-9a-f]{64}$'
   AND policy_sha256 IS NOT NULL AND program_id IS NOT NULL AND length(program_id)>0
   AND family_id IS NOT NULL AND length(family_id)>0 AND epoch_id IS NOT NULL
   AND eligible_at IS NOT NULL
   AND ((source_kind='official_record' AND official_record_id IS NOT NULL
         AND official_record_id=source_id AND intake_transition_id IS NULL)
     OR (source_kind='intake_transition' AND intake_transition_id IS NOT NULL
         AND intake_transition_id=source_id AND official_record_id IS NULL))) NOT VALID,
 ADD CONSTRAINT release_queue_published CHECK((state='published')=(published_report_id IS NOT NULL));
CREATE INDEX release_queue_ready ON eval.release_queue(eligible_at,id) WHERE state='pending';
REVOKE DELETE ON eval.release_queue FROM eval_rw;
CREATE FUNCTION eval.protect_release_source() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (NEW.id,NEW.payload,NEW.source_kind,NEW.source_id,NEW.source_sha256,NEW.policy_sha256,
     NEW.program_id,NEW.family_id,NEW.epoch_id,NEW.eligible_at,NEW.official_record_id,NEW.intake_transition_id)
   IS DISTINCT FROM
    (OLD.id,OLD.payload,OLD.source_kind,OLD.source_id,OLD.source_sha256,OLD.policy_sha256,
     OLD.program_id,OLD.family_id,OLD.epoch_id,OLD.eligible_at,OLD.official_record_id,OLD.intake_transition_id)
   OR OLD.state='published' THEN
   RAISE EXCEPTION 'release source or published outcome is immutable' USING ERRCODE='55000';
 END IF;
 RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION eval.protect_release_source() FROM PUBLIC;
CREATE TRIGGER release_source_frozen BEFORE UPDATE ON eval.release_queue
 FOR EACH ROW EXECUTE FUNCTION eval.protect_release_source();

ALTER TABLE eval.ladder_state ADD COLUMN scope_sha256 text UNIQUE,
 ADD CONSTRAINT ladder_metadata CHECK(scope_sha256 IS NOT NULL
   AND scope_sha256 ~ '^[0-9a-f]{64}$') NOT VALID;
REVOKE DELETE ON eval.ladder_state FROM eval_rw;
CREATE TABLE eval.release_publications (
 id uuid PRIMARY KEY REFERENCES eval.released_reports(id),
 queue_id uuid NOT NULL UNIQUE REFERENCES eval.release_queue(id),
 payload jsonb NOT NULL,created_by text NOT NULL,request_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),numeric_values integer NOT NULL CHECK(numeric_values>=0)
);
GRANT SELECT,INSERT ON eval.release_publications TO eval_rw;
CREATE TRIGGER release_publications_immutable BEFORE UPDATE OR DELETE ON eval.release_publications
 FOR EACH ROW EXECUTE FUNCTION eval.reject_mutation();
CREATE TRIGGER release_publications_no_truncate BEFORE TRUNCATE ON eval.release_publications
 FOR EACH STATEMENT EXECUTE FUNCTION eval.reject_mutation();
CREATE TRIGGER release_publications_audit AFTER INSERT ON eval.release_publications
 FOR EACH ROW EXECUTE FUNCTION eval.audit_write();
