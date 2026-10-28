CREATE TABLE eval.intake_campaigns (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, sha256 text NOT NULL,
 created_by text NOT NULL, request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 CHECK (sha256 ~ '^[0-9a-f]{64}$')
);

ALTER TABLE eval.intake ADD COLUMN campaign_id uuid REFERENCES eval.intake_campaigns(id),
 ADD COLUMN artifact_version_id uuid, ADD COLUMN published_seq bigint,
 ADD COLUMN program_id text, ADD COLUMN family_id text,
 ADD COLUMN semantic_scope_sha256 text, ADD COLUMN canonical_key text,
 ADD COLUMN state text, ADD COLUMN duplicate_of uuid REFERENCES eval.intake(id),
 ADD COLUMN feedback_disposition text, ADD COLUMN job_id uuid REFERENCES eval.jobs(id),
 ADD CONSTRAINT intake_unique_version UNIQUE (campaign_id,artifact_version_id),
 ADD CONSTRAINT intake_state CHECK (state IN
   ('discovered','deferred','queued','screening','duplicate','rejected','screen_passed','screen_failed')),
 ADD CONSTRAINT intake_feedback CHECK (feedback_disposition IN ('eligible','withheld:budget')),
 ADD CONSTRAINT intake_new_metadata CHECK (campaign_id IS NOT NULL AND artifact_version_id IS NOT NULL
   AND published_seq > 0 AND program_id <> '' AND family_id <> '' AND state IS NOT NULL) NOT VALID;
CREATE INDEX intake_pending ON eval.intake(campaign_id,state,published_seq);
CREATE INDEX intake_canonical ON eval.intake(semantic_scope_sha256,canonical_key,published_seq);
REVOKE DELETE ON eval.intake FROM eval_rw;

ALTER TABLE eval.intake_cursor ADD COLUMN campaign_id uuid UNIQUE REFERENCES eval.intake_campaigns(id),
 ADD COLUMN published_seq bigint NOT NULL DEFAULT 0 CHECK (published_seq >= 0),
 ADD COLUMN last_family text;
REVOKE DELETE ON eval.intake_cursor FROM eval_rw;

CREATE TABLE eval.intake_transitions (
 id uuid PRIMARY KEY, intake_id uuid NOT NULL REFERENCES eval.intake(id), payload jsonb NOT NULL,
 created_by text NOT NULL, request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE eval.intake_lineages (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, program_id text NOT NULL,
 family_id text NOT NULL, lineage_id text NOT NULL,
 created_by text NOT NULL, request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(program_id,family_id,lineage_id)
);
CREATE TABLE eval.intake_behavior (
 id uuid PRIMARY KEY, intake_id uuid NOT NULL UNIQUE REFERENCES eval.intake(id),
 semantic_scope_sha256 text NOT NULL, payload jsonb NOT NULL,
 created_by text NOT NULL, request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX intake_behavior_scope ON eval.intake_behavior(semantic_scope_sha256);
CREATE TABLE eval.feedback_reservations (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, program_id text NOT NULL,
 lineage_id text NOT NULL, generation_id text NOT NULL, artifact_version_id uuid NOT NULL,
 ordinal bigint NOT NULL CHECK (ordinal > 0),
 created_by text NOT NULL, request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(program_id,lineage_id,generation_id,artifact_version_id),
 UNIQUE(program_id,lineage_id,generation_id,ordinal)
);
DO $$
DECLARE t text;
BEGIN
 FOREACH t IN ARRAY ARRAY['intake_campaigns','intake_transitions','intake_lineages',
   'intake_behavior','feedback_reservations'] LOOP
  EXECUTE format('GRANT SELECT, INSERT ON eval.%I TO eval_rw',t);
  EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON eval.%I '
    'FOR EACH ROW EXECUTE FUNCTION eval.reject_mutation()',t || '_immutable',t);
  EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON eval.%I '
    'FOR EACH STATEMENT EXECUTE FUNCTION eval.reject_mutation()',t || '_no_truncate',t);
  EXECUTE format('CREATE TRIGGER %I AFTER INSERT ON eval.%I '
    'FOR EACH ROW EXECUTE FUNCTION eval.audit_write()',t || '_audit',t);
 END LOOP;
END;
$$;
