"""Append-only, explicitly authorized local data builds; no automatic campaign."""

from alembic import op

revision = "0009_authorized_ingest"
down_revision = "0008_delivery_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE eval.ingest_requests (
          id uuid PRIMARY KEY, program_id text NOT NULL, plan_sha256 text NOT NULL
            CHECK(plan_sha256 ~ '^[0-9a-f]{64}$'),
          authorization_sha256 text NOT NULL CHECK(authorization_sha256 ~ '^[0-9a-f]{64}$'),
          payload jsonb NOT NULL,created_by text NOT NULL,request_id uuid NOT NULL,
          created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE TABLE eval.ingest_outcomes (
          id uuid PRIMARY KEY, ingest_request_id uuid NOT NULL REFERENCES eval.ingest_requests(id),
          state text NOT NULL CHECK(state IN ('failed','built','catalog_available')),
          payload jsonb NOT NULL,created_by text NOT NULL,request_id uuid NOT NULL,
          created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE UNIQUE INDEX ingest_one_build ON eval.ingest_outcomes(ingest_request_id)
          WHERE state='built';
        CREATE UNIQUE INDEX ingest_one_catalog ON eval.ingest_outcomes(ingest_request_id)
          WHERE state='catalog_available';
        GRANT SELECT,INSERT ON eval.ingest_requests,eval.ingest_outcomes TO eval_rw;
        DO $$ DECLARE t text; BEGIN
          FOREACH t IN ARRAY ARRAY['ingest_requests','ingest_outcomes'] LOOP
            EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON eval.%I '
                           'FOR EACH ROW EXECUTE FUNCTION eval.reject_mutation()',
                           t||'_immutable',t);
            EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON eval.%I '
                           'FOR EACH STATEMENT EXECUTE FUNCTION eval.reject_mutation()',
                           t||'_no_truncate',t);
            EXECUTE format('CREATE TRIGGER %I AFTER INSERT ON eval.%I '
                           'FOR EACH ROW EXECUTE FUNCTION eval.audit_write()',t||'_audit',t);
          END LOOP;
        END; $$;
    """)


def downgrade() -> None:
    raise RuntimeError("Authorized ingest evidence cannot be downgraded")
