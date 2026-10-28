"""Immutable independent delivery attempts and a scoped signed-receipt view."""

from alembic import op

revision = "0008_delivery_evidence"
down_revision = "0007_signed_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE eval.delivery_attempts (
          id uuid PRIMARY KEY,
          job_id text NOT NULL CHECK(length(job_id)>0),
          program_id text NOT NULL CHECK(length(program_id)>0),
          proposal_id text NOT NULL CHECK(length(proposal_id)>0),
          attempt_sha256 text NOT NULL CHECK(attempt_sha256 ~ '^[0-9a-f]{64}$'),
          receipt_id uuid NOT NULL UNIQUE REFERENCES eval.delivery_receipts(id),
          receipt_sha256 text NOT NULL CHECK(receipt_sha256 ~ '^[0-9a-f]{64}$'),
          payload jsonb NOT NULL,created_by text NOT NULL,request_id uuid NOT NULL,
          created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
          UNIQUE(program_id,job_id,proposal_id)
        );
        GRANT SELECT,INSERT ON eval.delivery_attempts TO eval_rw;
        CREATE TRIGGER delivery_attempts_immutable
          BEFORE UPDATE OR DELETE ON eval.delivery_attempts
          FOR EACH ROW EXECUTE FUNCTION eval.reject_mutation();
        CREATE TRIGGER delivery_attempts_no_truncate
          BEFORE TRUNCATE ON eval.delivery_attempts
          FOR EACH STATEMENT EXECUTE FUNCTION eval.reject_mutation();
        CREATE TRIGGER delivery_attempts_audit AFTER INSERT ON eval.delivery_attempts
          FOR EACH ROW EXECUTE FUNCTION eval.audit_write();
        CREATE VIEW feedback.delivery_receipts_v WITH(security_barrier=true) AS
          SELECT r.id,a.program_id,a.job_id,a.proposal_id,r.payload,a.receipt_sha256,r.created_at
          FROM eval.delivery_receipts r JOIN eval.delivery_attempts a ON a.receipt_id=r.id
          WHERE a.program_id=ANY(string_to_array(
            coalesce(current_setting('qfr.program_ids',true),''),','));
        GRANT SELECT ON feedback.delivery_receipts_v TO feedback_ro;
        CREATE TRIGGER delivery_receipts_v_read_only
          INSTEAD OF INSERT OR UPDATE OR DELETE ON feedback.delivery_receipts_v
          FOR EACH ROW EXECUTE FUNCTION feedback.reject_view_write();
    """)


def downgrade() -> None:
    raise RuntimeError("Independent delivery evidence cannot be downgraded")
