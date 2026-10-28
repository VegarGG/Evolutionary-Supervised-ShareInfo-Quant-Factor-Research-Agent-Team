"""Preserve deferred request and source history through deletes and truncation."""

from alembic import op

revision = "0004_release_history_guards"
down_revision = "0003_release_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TRIGGER quota_requests_no_delete BEFORE DELETE ON eval.quota_requests
        FOR EACH ROW EXECUTE FUNCTION eval.reject_mutation();
        CREATE TRIGGER release_queue_no_delete BEFORE DELETE ON eval.release_queue
        FOR EACH ROW EXECUTE FUNCTION eval.reject_mutation();
        CREATE TRIGGER release_queue_no_truncate BEFORE TRUNCATE ON eval.release_queue
        FOR EACH STATEMENT EXECUTE FUNCTION eval.reject_mutation();
    """)


def downgrade() -> None:
    raise RuntimeError("Release history guards cannot be downgraded")
