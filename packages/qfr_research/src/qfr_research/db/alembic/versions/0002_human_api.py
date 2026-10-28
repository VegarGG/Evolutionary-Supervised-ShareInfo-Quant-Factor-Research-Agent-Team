"""Durable public research commands and released-only delivery references."""

from alembic import op

revision = "0002_human_api"
down_revision = "0001_blackboard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    DO $$ DECLARE t text; BEGIN
      FOREACH t IN ARRAY ARRAY['dataset_registrations','baseline_registrations',
        'protocol_proposals','manual_records','api_operations','delivery_proposals',
        'export_records'] LOOP
        EXECUTE format('CREATE TABLE research.%I (
          id uuid PRIMARY KEY,program_id uuid NOT NULL REFERENCES research.programs(id),
          payload jsonb NOT NULL,created_by text NOT NULL CHECK(length(btrim(created_by))>0),
          request_id uuid NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
          UNIQUE(id,program_id))',t);
        EXECUTE format('GRANT SELECT,INSERT ON research.%I TO research_rw',t);
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON research.%I
          FOR EACH ROW EXECUTE FUNCTION research.reject_mutation()',t||'_immutable',t);
        EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON research.%I
          FOR EACH STATEMENT EXECUTE FUNCTION research.reject_mutation()',t||'_no_truncate',t);
        EXECUTE format('CREATE TRIGGER %I AFTER INSERT ON research.%I
          FOR EACH ROW EXECUTE FUNCTION research.audit_write()',t||'_audit',t);
        EXECUTE format('CREATE INDEX %I ON research.%I(program_id,created_at,id)',
          t||'_program_time',t);
      END LOOP;
    END; $$;
    ALTER TABLE research.dataset_registrations
      ADD COLUMN registration_id text NOT NULL CHECK(registration_id ~ '^[0-9a-f]{64}$'),
      ADD COLUMN dataset_version_id text NOT NULL CHECK(dataset_version_id ~ '^[0-9a-f]{64}$'),
      ADD CONSTRAINT research_dataset_identity UNIQUE(program_id,dataset_version_id),
      ADD CONSTRAINT research_registration_identity UNIQUE(program_id,registration_id);
    ALTER TABLE research.baseline_registrations
      ADD COLUMN artifact_version_id uuid NOT NULL,
      ADD CONSTRAINT baseline_registration_identity UNIQUE(program_id,artifact_version_id);
    ALTER TABLE research.api_operations
      ADD COLUMN scope_key text NOT NULL,
      ADD COLUMN operation_key text NOT NULL,
      ADD COLUMN payload_hash text NOT NULL CHECK(payload_hash ~ '^[0-9a-f]{64}$'),
      ADD CONSTRAINT research_operation_key UNIQUE(program_id,scope_key,operation_key);
    ALTER TABLE research.delivery_proposals ADD COLUMN research_job_id uuid NOT NULL,
      ADD COLUMN sha256 text NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'),
      ADD FOREIGN KEY(research_job_id,program_id)
        REFERENCES research.research_jobs(id,program_id);
    ALTER TABLE research.export_records ADD COLUMN research_job_id uuid NOT NULL,
      ADD COLUMN archive bytea NOT NULL,
      ADD COLUMN archive_sha256 text NOT NULL CHECK(archive_sha256 ~ '^[0-9a-f]{64}$'),
      ADD FOREIGN KEY(research_job_id,program_id)
        REFERENCES research.research_jobs(id,program_id);
    ALTER TABLE research.research_jobs ADD COLUMN paused_from_state text;
    """)


def downgrade() -> None:
    raise RuntimeError("Research admission and delivery evidence cannot be downgraded")
