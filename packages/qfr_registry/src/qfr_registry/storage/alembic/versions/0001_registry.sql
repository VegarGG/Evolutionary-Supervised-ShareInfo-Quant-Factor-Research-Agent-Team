-- Legacy reservation rows remain unchanged. NOT VALID constraints preserve those
-- rows while requiring complete typed metadata for every subsequent publication.
ALTER TABLE registry.artifact_families
  ADD COLUMN program_id text,
  ADD COLUMN kind text,
  ADD COLUMN name text,
  ADD CONSTRAINT family_metadata CHECK (
    program_id IS NOT NULL AND length(program_id)>0 AND name IS NOT NULL
    AND name ~ '^[a-z0-9][a-z0-9_-]{0,63}$'
    AND kind IS NOT NULL AND kind IN ('factor','model','strategy','research_note','data_product')
  ) NOT VALID,
  ADD CONSTRAINT family_name UNIQUE (program_id,name);

CREATE SEQUENCE registry.publication_sequence;
REVOKE ALL ON SEQUENCE registry.publication_sequence FROM PUBLIC;
ALTER TABLE registry.artifact_versions
  ADD COLUMN family_id uuid REFERENCES registry.artifact_families(id),
  ADD COLUMN version_no integer,
  ADD COLUMN program_id text,
  ADD COLUMN kind text,
  ADD COLUMN canonical_hash text,
  ADD COLUMN implementation_hash text,
  ADD COLUMN implementation_kind text,
  ADD COLUMN payload_ref text,
  ADD COLUMN payload_digest text,
  ADD COLUMN published_seq bigint UNIQUE,
  ADD CONSTRAINT family_version UNIQUE (family_id,version_no),
  ADD CONSTRAINT version_metadata CHECK (
    id=artifact_version_id AND family_id IS NOT NULL
    AND version_no IS NOT NULL AND version_no>0
    AND program_id IS NOT NULL AND length(program_id)>0
    AND kind IS NOT NULL AND kind IN ('factor','model','strategy','research_note','data_product')
    AND (canonical_hash IS NULL OR canonical_hash ~ '^[0-9a-f]{64}$')
    AND implementation_hash IS NOT NULL AND implementation_hash ~ '^[0-9a-f]{64}$'
    AND implementation_kind IS NOT NULL
    AND implementation_kind IN ('dsl','constrained_python','fixed_composite',
      'declared_package_runner','document')
    AND payload_ref IS NOT NULL AND length(payload_ref)>0
    AND payload_digest IS NOT NULL AND payload_digest ~ '^[0-9a-f]{64}$'
    AND published_seq IS NOT NULL AND published_seq>0
  ) NOT VALID;
CREATE INDEX versions_program_sequence ON registry.artifact_versions(program_id,published_seq);
CREATE INDEX versions_canonical ON registry.artifact_versions(canonical_hash)
  WHERE canonical_hash IS NOT NULL;

-- Allocate sequence values only AFTER the publication transaction takes the lock.
-- A plain bigserial/default can expose a later commit before an earlier one and
-- make a since_seq reader permanently miss the earlier publication.
CREATE FUNCTION registry.assign_publication_sequence() RETURNS trigger LANGUAGE plpgsql
  SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
  PERFORM pg_advisory_xact_lock(72460302);
  IF NOT EXISTS (SELECT 1 FROM registry.artifact_families f WHERE f.id=NEW.family_id
      AND f.kind=NEW.kind AND f.program_id=NEW.program_id) THEN
    RAISE EXCEPTION 'publication family, kind and program must agree' USING ERRCODE='23514';
  END IF;
  NEW.published_seq := nextval('registry.publication_sequence'::regclass);
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION registry.assign_publication_sequence() FROM PUBLIC;
CREATE TRIGGER artifact_versions_sequence BEFORE INSERT ON registry.artifact_versions
  FOR EACH ROW EXECUTE FUNCTION registry.assign_publication_sequence();

ALTER TABLE registry.artifact_parents
  ADD COLUMN version_id uuid REFERENCES registry.artifact_versions(id),
  ADD COLUMN parent_version_id uuid REFERENCES registry.artifact_versions(id),
  ADD COLUMN relation text,
  ADD CONSTRAINT parent_pair UNIQUE(version_id,parent_version_id),
  ADD CONSTRAINT parent_metadata CHECK (
    version_id IS NOT NULL AND parent_version_id IS NOT NULL
    AND version_id<>parent_version_id AND relation IS NOT NULL
    AND relation IN ('seed','mutation','crossover','revision','repair','human_seed','import')
  ) NOT VALID;
CREATE FUNCTION registry.check_parent() RETURNS trigger LANGUAGE plpgsql
  SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM registry.artifact_versions child
      JOIN registry.artifact_versions parent ON parent.id=NEW.parent_version_id
      WHERE child.id=NEW.version_id AND parent.published_seq<child.published_seq
      AND parent.program_id=child.program_id) THEN
    RAISE EXCEPTION 'parent must be an earlier publication in the same program'
      USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION registry.check_parent() FROM PUBLIC;
CREATE TRIGGER artifact_parents_order BEFORE INSERT ON registry.artifact_parents
  FOR EACH ROW EXECUTE FUNCTION registry.check_parent();

CREATE TABLE registry.publication_requests (
  id uuid PRIMARY KEY,
  payload jsonb NOT NULL,
  created_by text NOT NULL,
  request_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  publish_key text NOT NULL CHECK(length(publish_key) BETWEEN 1 AND 200),
  request_digest text NOT NULL CHECK(request_digest ~ '^[0-9a-f]{64}$'),
  version_id uuid NOT NULL REFERENCES registry.artifact_versions(id),
  UNIQUE(created_by,publish_key)
);
CREATE TABLE registry.payload_objects (
  id uuid PRIMARY KEY,
  payload jsonb NOT NULL,
  created_by text NOT NULL,
  request_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  sha256 text NOT NULL UNIQUE CHECK(sha256 ~ '^[0-9a-f]{64}$'),
  object_ref text NOT NULL CHECK(length(object_ref)>0),
  size_bytes bigint NOT NULL CHECK(size_bytes>=0)
);

CREATE FUNCTION registry.audit_write() RETURNS trigger LANGUAGE plpgsql
  SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
  IF length(btrim(NEW.created_by))=0 THEN
    RAISE EXCEPTION 'write requires principal' USING ERRCODE='23514';
  END IF;
  INSERT INTO registry.registry_events(id,payload,created_by,request_id)
    VALUES(gen_random_uuid(),jsonb_build_object('action',TG_OP,
      'entity_type',TG_TABLE_NAME,'entity_id',NEW.id),NEW.created_by,NEW.request_id);
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION registry.audit_write() FROM PUBLIC;
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['publication_requests','payload_objects'] LOOP
    EXECUTE format('GRANT SELECT, INSERT ON registry.%I TO registry_app',t);
    EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON registry.%I '
      'FOR EACH ROW EXECUTE FUNCTION registry.reject_mutation()',t || '_immutable',t);
    EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON registry.%I '
      'FOR EACH STATEMENT EXECUTE FUNCTION registry.reject_mutation()',t || '_no_truncate',t);
  END LOOP;
  FOREACH t IN ARRAY ARRAY['artifact_families','artifact_versions','artifact_parents',
      'publication_requests','payload_objects','registry_events'] LOOP
    EXECUTE format('ALTER TABLE registry.%I ADD CONSTRAINT %I '
      'CHECK (length(btrim(created_by))>0) NOT VALID',t,t || '_principal');
    IF t<>'registry_events' THEN
      EXECUTE format('CREATE TRIGGER %I AFTER INSERT ON registry.%I '
        'FOR EACH ROW EXECUTE FUNCTION registry.audit_write()',t || '_audit',t);
    END IF;
  END LOOP;
END;
$$;
