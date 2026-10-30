"""Phase 0 foundation; domain tables are introduced in their assigned phases."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE FUNCTION reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'append-only table'; END; $$""")

    op.execute("""CREATE TABLE mcp_calls (
        call_id uuid PRIMARY KEY, at timestamptz NOT NULL, principal text NOT NULL,
        tool text NOT NULL, args_digest text NOT NULL CHECK (args_digest ~ '^[a-f0-9]{64}$'),
        args_size bigint NOT NULL CHECK (args_size >= 0),
        result_size bigint NOT NULL CHECK (result_size >= 0),
        duration_ms double precision NOT NULL CHECK (duration_ms >= 0),
        outcome text NOT NULL, error_code text, downstream_request_ids text[] NOT NULL,
        request_id text NOT NULL
    )""")
    op.execute("CREATE INDEX mcp_calls_request_idx ON mcp_calls(request_id)")
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON mcp_calls FROM control_rw")
    op.execute("""CREATE TRIGGER mcp_calls_immutable BEFORE UPDATE OR DELETE ON mcp_calls
        FOR EACH ROW EXECUTE FUNCTION reject_mutation()""")
    op.execute("""CREATE TRIGGER mcp_calls_no_truncate BEFORE TRUNCATE ON mcp_calls
        FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation()""")


def downgrade():
    raise RuntimeError("Foundation migrations are append-only; restore into a new database.")
