"""Keep an explicit read-only error independent of view updatability planning."""

from alembic import op

revision = "0006_feedback_write_guards"
down_revision = "0005_feedback_views"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION feedback.reject_view_write() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'feedback views are read only' USING ERRCODE='42501';
        END;
        $$;
        REVOKE ALL ON FUNCTION feedback.reject_view_write() FROM PUBLIC;
        DO $$
        DECLARE v text;
        BEGIN
          FOREACH v IN ARRAY ARRAY['released_reports_v','artifact_status_v','library_v',
                                  'policy_card_v','protocol_card_v'] LOOP
            EXECUTE format('CREATE TRIGGER %I INSTEAD OF INSERT OR UPDATE OR DELETE ON feedback.%I '
                           'FOR EACH ROW EXECUTE FUNCTION feedback.reject_view_write()',
                           v || '_read_only',v);
          END LOOP;
        END;
        $$;
    """)


def downgrade() -> None:
    raise RuntimeError("Feedback write guards cannot be downgraded")
