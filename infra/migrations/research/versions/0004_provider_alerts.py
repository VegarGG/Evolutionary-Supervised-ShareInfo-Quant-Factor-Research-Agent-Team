"""Phase 7 research_db: provider alerts (PLAN Sections 11.8 and 17.4).

Repeated fallbacks away from one model and failed provider probes raise an alert that
the owner reads in qfr.ops.alerts and acknowledges with qfr.ops.acknowledge_alert. An
alert is raised once per dedup key and never deleted; like the evaluator's alerts, the
only change the table allows is acknowledgement.
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE provider_alerts (
        alert_id uuid PRIMARY KEY,
        kind text NOT NULL CHECK (kind IN ('provider_fallback', 'probe_failed')),
        dedup_key text NOT NULL UNIQUE,
        at timestamptz NOT NULL,
        details jsonb NOT NULL,
        state text NOT NULL CHECK (state IN ('open', 'acknowledged')),
        acknowledged_by text,
        acknowledged_at timestamptz,
        note text CHECK (note IS NULL OR length(note) BETWEEN 1 AND 2000),
        request_id text NOT NULL,
        CHECK ((state = 'acknowledged') = (acknowledged_at IS NOT NULL))
    )""")
    op.execute("CREATE INDEX provider_alerts_state_idx ON provider_alerts (state, at)")
    op.execute("REVOKE DELETE, TRUNCATE ON provider_alerts FROM research_rw")
    op.execute("""CREATE FUNCTION guard_provider_alert() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP <> 'UPDATE' THEN RAISE EXCEPTION 'alerts are never deleted'; END IF;
            IF OLD.state <> 'open' OR NEW.state <> 'acknowledged'
               OR (to_jsonb(NEW) - ARRAY['state', 'acknowledged_by', 'acknowledged_at', 'note'])
                  IS DISTINCT FROM
                  (to_jsonb(OLD) - ARRAY['state', 'acknowledged_by', 'acknowledged_at', 'note'])
            THEN
                RAISE EXCEPTION 'an alert can only be acknowledged';
            END IF;
            RETURN NEW;
        END; $$""")
    op.execute("""CREATE TRIGGER provider_alerts_guard BEFORE UPDATE OR DELETE ON provider_alerts
        FOR EACH ROW EXECUTE FUNCTION guard_provider_alert()""")
    op.execute("""CREATE TRIGGER provider_alerts_no_truncate BEFORE TRUNCATE ON provider_alerts
        FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation()""")


def downgrade():
    raise RuntimeError("Research migrations are append-only; restore into a new database.")
