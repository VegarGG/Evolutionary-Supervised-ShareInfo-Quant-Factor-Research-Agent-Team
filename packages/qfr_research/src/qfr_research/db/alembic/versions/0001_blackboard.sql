-- The Stage 0 bootstrap remains unchanged. NOT VALID checks retain historical
-- reservation rows, while every new/changed row must satisfy the typed schema.
ALTER TABLE research.programs
  ADD COLUMN name text,
  ADD COLUMN status text NOT NULL DEFAULT 'inactive'
    CHECK(status IN ('inactive','active','paused')),
  ADD COLUMN charter jsonb,
  ADD COLUMN charter_revision integer,
  ADD CONSTRAINT program_metadata CHECK(name IS NOT NULL AND length(btrim(name))>0
    AND charter IS NOT NULL AND jsonb_typeof(charter)='object'
    AND charter_revision IS NOT NULL AND charter_revision>0) NOT VALID;

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['program_revisions','briefs','checkpoints','checkpoint_answers'] LOOP
    EXECUTE format('CREATE TABLE research.%I (
      id uuid PRIMARY KEY, payload jsonb NOT NULL, created_by text NOT NULL,
      request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now())',t);
    EXECUTE format('GRANT SELECT, INSERT ON research.%I TO research_rw',t);
  END LOOP;
  GRANT UPDATE ON research.checkpoints TO research_rw;
END;
$$;

-- Composite foreign keys below prohibit cross-program entity references. Shared
-- publication/report IDs are opaque references, never cross-database writes.
DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='research'
      AND tablename NOT IN ('programs','events','alembic_version') LOOP
    EXECUTE format('ALTER TABLE research.%I
      ADD COLUMN program_id uuid REFERENCES research.programs(id),
      ADD CONSTRAINT %I CHECK(program_id IS NOT NULL) NOT VALID,
      ADD CONSTRAINT %I UNIQUE(id,program_id)',t,t||'_program_required',t||'_scoped_id');
    EXECUTE format('CREATE INDEX %I ON research.%I (program_id,created_at,id)',
      t||'_program_created',t);
  END LOOP;
END;
$$;

ALTER TABLE research.program_revisions
  ADD COLUMN revision integer NOT NULL CHECK(revision>0),
  ADD COLUMN sha256 text NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'),
  ADD CONSTRAINT program_revision_unique UNIQUE(program_id,revision);
ALTER TABLE research.islands ADD COLUMN key text, ADD COLUMN theme text,
  ADD COLUMN status text NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused')),
  ADD CONSTRAINT island_key_unique UNIQUE(program_id,key),
  ADD CONSTRAINT island_metadata CHECK(key IS NOT NULL AND length(key)>0
    AND theme IS NOT NULL AND length(theme)>0) NOT VALID;
ALTER TABLE research.generations ADD COLUMN seq integer, ADD COLUMN state text,
  ADD COLUMN started_at timestamptz, ADD COLUMN ended_at timestamptz,
  ADD CONSTRAINT generation_sequence UNIQUE(program_id,seq),
  ADD CONSTRAINT generation_metadata CHECK(seq IS NOT NULL AND seq>0
    AND state IS NOT NULL AND length(state)>0) NOT VALID;
ALTER TABLE research.tasks ADD COLUMN generation_id uuid, ADD COLUMN island_id uuid,
  ADD COLUMN type text, ADD COLUMN state text NOT NULL DEFAULT 'pending',
  ADD COLUMN attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0), ADD COLUMN error_code text,
  ADD FOREIGN KEY(generation_id,program_id) REFERENCES research.generations(id,program_id),
  ADD FOREIGN KEY(island_id,program_id) REFERENCES research.islands(id,program_id),
  ADD CONSTRAINT task_type CHECK(type IS NOT NULL AND length(type)>0) NOT VALID;
ALTER TABLE research.hypotheses ADD COLUMN island_id uuid, ADD COLUMN parent_hypothesis_id uuid,
  ADD COLUMN status text NOT NULL DEFAULT 'open'
    CHECK(status IN ('open','supported','weakened','retired')),
  ADD FOREIGN KEY(island_id,program_id) REFERENCES research.islands(id,program_id),
  ADD FOREIGN KEY(parent_hypothesis_id,program_id) REFERENCES research.hypotheses(id,program_id);
ALTER TABLE research.candidates ADD COLUMN task_id uuid, ADD COLUMN hypothesis_id uuid,
  ADD COLUMN island_id uuid, ADD COLUMN state text NOT NULL DEFAULT 'draft',
  ADD COLUMN canonical_hash text CHECK(canonical_hash ~ '^[0-9a-f]{64}$'),
  ADD COLUMN artifact_version_id text,
  ADD FOREIGN KEY(task_id,program_id) REFERENCES research.tasks(id,program_id),
  ADD FOREIGN KEY(hypothesis_id,program_id) REFERENCES research.hypotheses(id,program_id),
  ADD FOREIGN KEY(island_id,program_id) REFERENCES research.islands(id,program_id);
ALTER TABLE research.reviews ADD COLUMN candidate_id uuid, ADD COLUMN round integer,
  ADD COLUMN verdict text CHECK(verdict IN ('approve','revise','reject')),
  ADD FOREIGN KEY(candidate_id,program_id) REFERENCES research.candidates(id,program_id),
  ADD CONSTRAINT review_metadata CHECK(candidate_id IS NOT NULL AND round IS NOT NULL
    AND round>0 AND verdict IS NOT NULL) NOT VALID;
ALTER TABLE research.population_members ADD COLUMN island_id uuid, ADD COLUMN version_id text,
  ADD COLUMN status text NOT NULL DEFAULT 'provisional'
    CHECK(status IN ('official','provisional','archived')),
  ADD FOREIGN KEY(island_id,program_id) REFERENCES research.islands(id,program_id),
  ADD CONSTRAINT population_version UNIQUE(program_id,version_id),
  ADD CONSTRAINT population_reference CHECK(version_id IS NOT NULL) NOT VALID;
ALTER TABLE research.archive_cells ADD COLUMN cell_key text, ADD COLUMN elite_version_id text,
  ADD CONSTRAINT archive_cell UNIQUE(program_id,cell_key),
  ADD CONSTRAINT archive_metadata CHECK(cell_key IS NOT NULL AND elite_version_id IS NOT NULL)
    NOT VALID;
ALTER TABLE research.lineage_edges ADD COLUMN child_version_id text,
  ADD COLUMN parent_version_id text, ADD COLUMN relation text, ADD COLUMN operator text,
  ADD CONSTRAINT lineage_edge UNIQUE(program_id,child_version_id,parent_version_id,relation),
  ADD CONSTRAINT lineage_metadata CHECK(child_version_id IS NOT NULL
    AND parent_version_id IS NOT NULL AND relation IS NOT NULL
    AND child_version_id<>parent_version_id) NOT VALID;
ALTER TABLE research.report_cache ADD COLUMN report_id text, ADD COLUMN version_id text,
  ADD COLUMN report_type text, ADD COLUMN released_at timestamptz,
  ADD COLUMN content_hash text CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  ADD CONSTRAINT report_cache_identity UNIQUE(program_id,report_id),
  ADD CONSTRAINT report_cache_metadata CHECK(report_id IS NOT NULL AND version_id IS NOT NULL
    AND report_type IS NOT NULL AND released_at IS NOT NULL AND content_hash IS NOT NULL) NOT VALID;
ALTER TABLE research.report_links ADD COLUMN report_cache_id uuid,
  ADD COLUMN entity_type text, ADD COLUMN entity_id uuid,
  ADD FOREIGN KEY(report_cache_id,program_id) REFERENCES research.report_cache(id,program_id),
  ADD CONSTRAINT report_link_metadata CHECK(report_cache_id IS NOT NULL
    AND entity_type IS NOT NULL AND entity_id IS NOT NULL) NOT VALID;
ALTER TABLE research.feedback_cursor ADD COLUMN last_released_at timestamptz,
  ADD COLUMN last_report_id text, ADD CONSTRAINT feedback_program UNIQUE(program_id);
ALTER TABLE research.interpretations ADD COLUMN version_id text,
  ADD COLUMN status text NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','challenged','final'));
ALTER TABLE research.interpretation_challenges ADD COLUMN interpretation_id uuid,
  ADD COLUMN verdict text CHECK(verdict IN ('accept','amend')),
  ADD FOREIGN KEY(interpretation_id,program_id) REFERENCES research.interpretations(id,program_id),
  ADD CONSTRAINT challenge_metadata CHECK(interpretation_id IS NOT NULL AND verdict IS NOT NULL)
    NOT VALID;
ALTER TABLE research.knowledge_items ADD COLUMN kind text
    CHECK(kind IN ('failure_mode','insight','anti_pattern','rejected_idea')),
  ADD CONSTRAINT knowledge_kind CHECK(kind IS NOT NULL) NOT VALID;
ALTER TABLE research.bandit_state ADD COLUMN island_id uuid,
  ADD COLUMN alpha double precision CHECK(alpha>0 AND alpha<'Infinity'::float8),
  ADD COLUMN beta double precision CHECK(beta>0 AND beta<'Infinity'::float8),
  ADD FOREIGN KEY(island_id,program_id) REFERENCES research.islands(id,program_id),
  ADD CONSTRAINT bandit_island UNIQUE(program_id,island_id);
ALTER TABLE research.budget_ledger ADD COLUMN generation_id uuid, ADD COLUMN task_id uuid,
  ADD COLUMN role text, ADD COLUMN model text, ADD COLUMN tokens_in bigint CHECK(tokens_in>=0),
  ADD COLUMN tokens_out bigint CHECK(tokens_out>=0),
  ADD COLUMN cost_usd numeric CHECK(cost_usd>=0 AND cost_usd<'Infinity'::numeric),
  ADD FOREIGN KEY(generation_id,program_id) REFERENCES research.generations(id,program_id),
  ADD FOREIGN KEY(task_id,program_id) REFERENCES research.tasks(id,program_id);
ALTER TABLE research.agent_runs ADD COLUMN task_id uuid, ADD COLUMN role text,
  ADD COLUMN model text, ADD COLUMN status text,
  ADD FOREIGN KEY(task_id,program_id) REFERENCES research.tasks(id,program_id);

ALTER TABLE research.input_bundles ADD COLUMN bundle_key text, ADD COLUMN sha256 text,
  ADD CONSTRAINT bundle_identity UNIQUE(program_id,bundle_key),
  ADD CONSTRAINT bundle_metadata CHECK(bundle_key IS NOT NULL
    AND sha256 IS NOT NULL AND sha256 ~ '^[0-9a-f]{64}$') NOT VALID;
ALTER TABLE research.source_assets ADD COLUMN asset_key text, ADD COLUMN sha256 text,
  ADD COLUMN size_bytes bigint CHECK(size_bytes>=0),
  ADD CONSTRAINT source_asset_identity UNIQUE(program_id,asset_key),
  ADD CONSTRAINT source_asset_metadata CHECK(asset_key IS NOT NULL AND sha256 IS NOT NULL
    AND sha256 ~ '^[0-9a-f]{64}$' AND size_bytes IS NOT NULL) NOT VALID;
ALTER TABLE research.briefs ADD COLUMN sha256 text NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'),
  ADD COLUMN input_bundle_id uuid NOT NULL,
  ADD FOREIGN KEY(input_bundle_id,program_id) REFERENCES research.input_bundles(id,program_id);
ALTER TABLE research.research_jobs ADD COLUMN input_bundle_id uuid, ADD COLUMN brief_id uuid,
  ADD COLUMN idempotency_key text, ADD COLUMN payload_hash text, ADD COLUMN config_hash text,
  ADD COLUMN gate_spec_hash text, ADD COLUMN delivery_ref_id uuid,
  ADD COLUMN state text NOT NULL DEFAULT 'received' CHECK(state IN
    ('received','validating','ready','running','awaiting_evaluation','validating_delivery',
     'completed','needs_input','paused','budget_paused','waiting_for_data','failed','cancelled')),
  ADD COLUMN revision bigint NOT NULL DEFAULT 1 CHECK(revision>0),
  ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now(),
  ADD FOREIGN KEY(input_bundle_id,program_id) REFERENCES research.input_bundles(id,program_id),
  ADD FOREIGN KEY(brief_id,program_id) REFERENCES research.briefs(id,program_id),
  ADD CONSTRAINT research_admission_key UNIQUE(program_id,idempotency_key),
  ADD CONSTRAINT research_job_metadata CHECK(input_bundle_id IS NOT NULL AND brief_id IS NOT NULL
    AND idempotency_key IS NOT NULL AND length(idempotency_key)>0
    AND payload_hash IS NOT NULL AND payload_hash ~ '^[0-9a-f]{64}$'
    AND config_hash IS NOT NULL AND config_hash ~ '^[0-9a-f]{64}$'
    AND gate_spec_hash IS NOT NULL AND gate_spec_hash ~ '^[0-9a-f]{64}$') NOT VALID;
ALTER TABLE research.delivery_refs ADD COLUMN research_job_id uuid, ADD COLUMN receipt_id text,
  ADD COLUMN gate_spec_hash text, ADD COLUMN receipt_sha256 text,
  ADD COLUMN result text CHECK(result IN ('pass','fail')), ADD COLUMN verification_key_id text,
  ADD FOREIGN KEY(research_job_id,program_id) REFERENCES research.research_jobs(id,program_id),
  ADD CONSTRAINT delivery_receipt_unique UNIQUE(program_id,receipt_id),
  ADD CONSTRAINT delivery_ref_metadata CHECK(research_job_id IS NOT NULL AND receipt_id IS NOT NULL
    AND gate_spec_hash IS NOT NULL AND gate_spec_hash ~ '^[0-9a-f]{64}$'
    AND receipt_sha256 IS NOT NULL AND receipt_sha256 ~ '^[0-9a-f]{64}$'
    AND result IS NOT NULL AND verification_key_id IS NOT NULL
    AND length(verification_key_id)>0) NOT VALID;
ALTER TABLE research.research_jobs ADD FOREIGN KEY(delivery_ref_id,program_id)
  REFERENCES research.delivery_refs(id,program_id);
ALTER TABLE research.checkpoints ADD COLUMN research_job_id uuid NOT NULL,
  ADD COLUMN state text NOT NULL DEFAULT 'open' CHECK(state IN ('open','answered')),
  ADD FOREIGN KEY(research_job_id,program_id) REFERENCES research.research_jobs(id,program_id);
ALTER TABLE research.checkpoint_answers ADD COLUMN checkpoint_id uuid NOT NULL,
  ADD FOREIGN KEY(checkpoint_id,program_id) REFERENCES research.checkpoints(id,program_id),
  ADD CONSTRAINT checkpoint_answer_unique UNIQUE(checkpoint_id);
ALTER TABLE research.provider_profiles ADD COLUMN profile_key text, ADD COLUMN revision integer,
  ADD COLUMN sha256 text CHECK(sha256 ~ '^[0-9a-f]{64}$'),
  ADD CONSTRAINT provider_revision UNIQUE(program_id,profile_key,revision);
ALTER TABLE research.role_profiles ADD COLUMN profile_key text, ADD COLUMN revision integer,
  ADD COLUMN sha256 text CHECK(sha256 ~ '^[0-9a-f]{64}$'),
  ADD CONSTRAINT role_revision UNIQUE(program_id,profile_key,revision);
ALTER TABLE research.llm_attempts ADD COLUMN task_id uuid, ADD COLUMN status text,
  ADD FOREIGN KEY(task_id,program_id) REFERENCES research.tasks(id,program_id);

-- A queue task is never a research job completion. No wall-clock/generation cap
-- is introduced. Only explicit admission creates a queue entry.
ALTER TABLE research.jobs ADD COLUMN research_job_id uuid, ADD COLUMN queue text,
  ADD COLUMN enqueue_key text, ADD COLUMN payload_hash text,
  ADD COLUMN state text NOT NULL DEFAULT 'queued'
    CHECK(state IN ('queued','running','complete','failed','cancelled')),
  ADD COLUMN run_after timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
  ADD COLUMN fence bigint NOT NULL DEFAULT 0 CHECK(fence>=0),
  ADD COLUMN locked_by text, ADD COLUMN lease_until timestamptz,
  ADD FOREIGN KEY(research_job_id,program_id) REFERENCES research.research_jobs(id,program_id),
  ADD CONSTRAINT research_enqueue_key UNIQUE(program_id,queue,enqueue_key),
  ADD CONSTRAINT research_queue_lease CHECK((state='running')=
    (locked_by IS NOT NULL AND lease_until IS NOT NULL)),
  ADD CONSTRAINT research_queue_metadata CHECK(research_job_id IS NOT NULL AND queue IS NOT NULL
    AND length(queue)>0 AND enqueue_key IS NOT NULL AND length(enqueue_key)>0
    AND payload_hash IS NOT NULL AND payload_hash ~ '^[0-9a-f]{64}$') NOT VALID;
CREATE INDEX research_queue_ready ON research.jobs(queue,run_after,created_at,id)
  WHERE state IN ('queued','running');
CREATE INDEX research_queue_parent ON research.jobs(research_job_id,program_id);
CREATE INDEX research_job_states ON research.research_jobs(program_id,state,created_at,id);
ALTER TABLE research.events ADD COLUMN program_id uuid REFERENCES research.programs(id);
CREATE INDEX research_events_program ON research.events(program_id,created_at,id);

CREATE FUNCTION research.protect_job_intent() RETURNS trigger LANGUAGE plpgsql
  SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
  IF NOT EXISTS(SELECT 1 FROM research.briefs b WHERE b.id=NEW.brief_id
      AND b.program_id=NEW.program_id AND b.input_bundle_id=NEW.input_bundle_id) THEN
    RAISE EXCEPTION 'job brief and input bundle must agree' USING ERRCODE='23514';
  END IF;
  IF TG_OP='UPDATE' AND (NEW.program_id,NEW.input_bundle_id,NEW.brief_id,
      NEW.idempotency_key,NEW.payload_hash,NEW.config_hash,NEW.gate_spec_hash)
    IS DISTINCT FROM (OLD.program_id,OLD.input_bundle_id,OLD.brief_id,
      OLD.idempotency_key,OLD.payload_hash,OLD.config_hash,OLD.gate_spec_hash) THEN
    RAISE EXCEPTION 'admitted job intent is frozen' USING ERRCODE='55000';
  END IF;
  IF NEW.state='completed' AND NOT EXISTS(SELECT 1 FROM research.delivery_refs r
    WHERE r.id=NEW.delivery_ref_id AND r.program_id=NEW.program_id
      AND r.research_job_id=NEW.id AND r.gate_spec_hash=NEW.gate_spec_hash AND r.result='pass') THEN
    RAISE EXCEPTION 'completion requires the verified independent receipt'
      USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION research.protect_job_intent() FROM PUBLIC;
CREATE TRIGGER research_job_intent BEFORE INSERT OR UPDATE ON research.research_jobs
  FOR EACH ROW EXECUTE FUNCTION research.protect_job_intent();

CREATE FUNCTION research.audit_write() RETURNS trigger LANGUAGE plpgsql
  SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE principal text; request text; rowdata jsonb; project uuid;
BEGIN
  principal:=current_setting('qfr.principal',true);
  request:=current_setting('qfr.request_id',true);
  IF coalesce(length(btrim(principal)),0)=0 OR coalesce(length(request),0)=0 THEN
    RAISE EXCEPTION 'write requires transaction principal and request id' USING ERRCODE='23514';
  END IF;
  IF TG_OP='INSERT' AND (NEW.created_by<>principal OR NEW.request_id<>request::uuid) THEN
    RAISE EXCEPTION 'row attribution differs from request' USING ERRCODE='23514';
  END IF;
  IF TG_OP='UPDATE' THEN
    IF (NEW.id,NEW.created_by,NEW.request_id,NEW.created_at)
        IS DISTINCT FROM (OLD.id,OLD.created_by,OLD.request_id,OLD.created_at)
        OR (to_jsonb(NEW)->>'program_id') IS DISTINCT FROM (to_jsonb(OLD)->>'program_id') THEN
      RAISE EXCEPTION 'original write identity and program are immutable' USING ERRCODE='55000';
    END IF;
  END IF;
  rowdata:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
  project:=CASE WHEN TG_TABLE_NAME='programs' THEN (rowdata->>'id')::uuid
    ELSE (rowdata->>'program_id')::uuid END;
  INSERT INTO research.events(id,payload,created_by,request_id,program_id)
    VALUES(gen_random_uuid(),jsonb_build_object('action',TG_OP,'entity_type',TG_TABLE_NAME,
      'entity_id',rowdata->>'id'),principal,request::uuid,project);
  RETURN COALESCE(NEW,OLD);
END;
$$;
REVOKE ALL ON FUNCTION research.audit_write() FROM PUBLIC;
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['program_revisions','briefs','checkpoint_answers'] LOOP
    EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON research.%I
      FOR EACH ROW EXECUTE FUNCTION research.reject_mutation()',t||'_immutable',t);
    EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON research.%I
      FOR EACH STATEMENT EXECUTE FUNCTION research.reject_mutation()',t||'_no_truncate',t);
  END LOOP;
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='research'
      AND tablename<>'alembic_version' LOOP
    EXECUTE format('ALTER TABLE research.%I ADD CONSTRAINT %I
      CHECK(length(btrim(created_by))>0) NOT VALID',t,t||'_principal');
    IF t<>'events' THEN
      -- Keep history rather than allowing a context deletion to orphan evidence.
      EXECUTE format('REVOKE DELETE ON research.%I FROM research_rw',t);
      EXECUTE format('CREATE TRIGGER %I AFTER INSERT OR UPDATE OR DELETE ON research.%I
        FOR EACH ROW EXECUTE FUNCTION research.audit_write()',t||'_audit',t);
    END IF;
  END LOOP;
END;
$$;
