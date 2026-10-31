"""Phase 7 control_db: deliveries, operations alerts, alert acknowledgements and the
nightly operations runs (PLAN Sections 13.4, 15.4, 16.4 and 17.4).

All four tables are insert-only. A delivery records one deliverable bundle written to
exports/. An operations alert is raised once per dedup key by the nightly job (disk
guard, missing backups). An acknowledgement is the owner's record that they saw an
alert from any zone: evaluation and research alerts also change state in their own
database, operations alerts are acknowledged by this row alone. A nightly run records
what the log maintenance and the backup check found.
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TABLES = ("deliveries", "ops_alerts", "alert_acks", "ops_runs")


def upgrade():
    op.execute("""CREATE TABLE deliveries (
        delivery_id uuid PRIMARY KEY,
        deliverable_id uuid NOT NULL,
        job_id uuid NOT NULL,
        fetched_at timestamptz NOT NULL,
        exported_path text NOT NULL CHECK (length(exported_path) BETWEEN 1 AND 500),
        export_sha256 text NOT NULL CHECK (export_sha256 ~ '^[0-9a-f]{64}$'),
        files integer NOT NULL CHECK (files > 0),
        principal text NOT NULL,
        request_id text NOT NULL
    )""")
    op.execute("CREATE INDEX deliveries_deliverable_idx ON deliveries (deliverable_id, fetched_at)")
    op.execute("""CREATE TABLE ops_alerts (
        alert_id uuid PRIMARY KEY,
        kind text NOT NULL CHECK (kind IN ('disk', 'backup')),
        dedup_key text NOT NULL UNIQUE,
        at timestamptz NOT NULL,
        details jsonb NOT NULL,
        principal text NOT NULL,
        request_id text NOT NULL
    )""")
    op.execute("CREATE INDEX ops_alerts_at_idx ON ops_alerts (at DESC, alert_id)")
    op.execute("""CREATE TABLE alert_acks (
        ack_id uuid PRIMARY KEY,
        source text NOT NULL CHECK (source IN ('evaluation', 'research', 'operations')),
        alert_id uuid NOT NULL,
        at timestamptz NOT NULL,
        note text CHECK (note IS NULL OR length(note) BETWEEN 1 AND 2000),
        principal text NOT NULL,
        request_id text NOT NULL,
        UNIQUE (source, alert_id)
    )""")
    op.execute("""CREATE TABLE ops_runs (
        run_id uuid PRIMARY KEY,
        at timestamptz NOT NULL,
        kind text NOT NULL CHECK (kind IN ('nightly')),
        due_at timestamptz NOT NULL,
        report jsonb NOT NULL,
        request_id text NOT NULL
    )""")
    op.execute("CREATE INDEX ops_runs_kind_idx ON ops_runs (kind, due_at DESC)")
    for table in TABLES:
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM control_rw")
        op.execute(f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_mutation()""")
        op.execute(f"""CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation()""")


def downgrade():
    raise RuntimeError("Control migrations are append-only; restore into a new database.")
