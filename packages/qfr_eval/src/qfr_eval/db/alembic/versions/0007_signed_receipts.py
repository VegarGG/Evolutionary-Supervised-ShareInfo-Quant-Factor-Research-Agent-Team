"""Add immutable private authenticity wrappers without rewriting earlier evidence."""

from alembic import op

revision = "0007_signed_receipts"
down_revision = "0006_feedback_write_guards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE eval.signed_measurement_receipts (
          id uuid PRIMARY KEY,
          official_record_id uuid NOT NULL UNIQUE REFERENCES eval.official_records(id),
          original_receipt_hash text NOT NULL CHECK(original_receipt_hash ~ '^[0-9a-f]{64}$'),
          payload_sha256 text NOT NULL CHECK(payload_sha256 ~ '^[0-9a-f]{64}$'),
          payload jsonb NOT NULL,created_by text NOT NULL,request_id uuid NOT NULL,
          created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        GRANT SELECT,INSERT ON eval.signed_measurement_receipts TO eval_rw;
        CREATE TRIGGER signed_measurement_receipts_immutable
          BEFORE UPDATE OR DELETE ON eval.signed_measurement_receipts
          FOR EACH ROW EXECUTE FUNCTION eval.reject_mutation();
        CREATE TRIGGER signed_measurement_receipts_no_truncate
          BEFORE TRUNCATE ON eval.signed_measurement_receipts
          FOR EACH STATEMENT EXECUTE FUNCTION eval.reject_mutation();
        CREATE TRIGGER signed_measurement_receipts_audit
          AFTER INSERT ON eval.signed_measurement_receipts
          FOR EACH ROW EXECUTE FUNCTION eval.audit_write();
    """)


def downgrade() -> None:
    raise RuntimeError("Signed evidence wrappers cannot be downgraded")
