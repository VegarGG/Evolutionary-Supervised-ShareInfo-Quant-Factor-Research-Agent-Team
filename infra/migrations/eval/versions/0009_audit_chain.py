"""Phase 8 eval_db (P8.5): a hash chain over the evaluator's audit, eval.events (every
configuration, intake, gate, acceptance and alert decision).

The audit tables were already insert-only. The chain makes a change made around those
rules visible: audit_seal() appends one link per audit row not linked yet, in time
order, and each link is SHA-256 over the previous link, its position, the row's table
and id, and the digest of the row's JSON. audit_verify() walks the chain and recomputes
every link and every row digest; an edited, deleted or reordered row breaks it. The
backup service seals and verifies before each dump and records the chain head with the
backup, so a later rewrite of the whole chain does not match earlier backups either.
Application roles cannot read or write the chain; the migration role seals it.
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

SCHEMA = "eval"
TABLES = (("events", "event_id", "at"),)
APP_ROLES = "eval_rw, feedback_ro"

# The audit chain, the same in each audited database (copied, not imported, so this
# migration never changes after it ships).
ZERO = "0" * 64


def _chain_sql(schema: str, tables: tuple[tuple[str, str, str], ...], app_roles: str) -> list[str]:
    """tables: (table, id column, time column). One chain per database, sealed in time
    order, then table name, then id."""
    unsealed = " UNION ALL ".join(
        f"SELECT '{t}'::text AS tbl, s.{i} AS id, s.{a} AS at, to_jsonb(s) AS doc "
        f"FROM {schema}.{t} s WHERE NOT EXISTS (SELECT 1 FROM {schema}.audit_chain c "
        f"WHERE c.table_name = '{t}' AND c.row_id = s.{i})"
        for t, i, a in tables
    )
    changed = " UNION ALL ".join(
        f"SELECT c.chain_seq, s.{i} IS NULL AS missing FROM {schema}.audit_chain c "
        f"LEFT JOIN {schema}.{t} s ON s.{i} = c.row_id WHERE c.table_name = '{t}' AND "
        f"(s.{i} IS NULL OR {schema}.audit_digest(to_jsonb(s)) <> c.row_digest)"
        for t, i, _ in tables
    )
    settings = (
        f"SET timezone TO 'UTC' SET extra_float_digits TO 1 SET search_path TO {schema}, pg_temp"
    )
    return [
        f"""CREATE TABLE {schema}.audit_chain (
            chain_seq bigint PRIMARY KEY CHECK (chain_seq >= 1),
            table_name text NOT NULL,
            row_id uuid NOT NULL,
            row_digest text NOT NULL CHECK (row_digest ~ '^[a-f0-9]{{64}}$'),
            prev_hash text NOT NULL CHECK (prev_hash ~ '^[a-f0-9]{{64}}$'),
            link_hash text NOT NULL CHECK (link_hash ~ '^[a-f0-9]{{64}}$'),
            sealed_at timestamptz NOT NULL,
            UNIQUE (table_name, row_id)
        )""",
        f"REVOKE ALL ON {schema}.audit_chain FROM {app_roles}",
        f"""CREATE TRIGGER audit_chain_immutable BEFORE UPDATE OR DELETE ON {schema}.audit_chain
            FOR EACH ROW EXECUTE FUNCTION public.reject_mutation()""",
        f"""CREATE TRIGGER audit_chain_no_truncate BEFORE TRUNCATE ON {schema}.audit_chain
            FOR EACH STATEMENT EXECUTE FUNCTION public.reject_mutation()""",
        # A row's digest: SHA-256 of its JSON text, with timestamps in UTC (the callers
        # pin the time zone and float output, so the text is the same on any server).
        f"""CREATE FUNCTION {schema}.audit_digest(doc jsonb) RETURNS text LANGUAGE sql
            IMMUTABLE AS $$ SELECT encode(sha256(convert_to(doc::text, 'UTF8')), 'hex') $$""",
        f"""CREATE FUNCTION {schema}.audit_link(prev text, seq bigint, tbl text, id uuid,
            digest text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
            SELECT encode(sha256(convert_to(prev || ':' || seq || ':' || tbl || ':' || id
                || ':' || digest, 'UTF8')), 'hex') $$""",
        # Append a link for every audit row not in the chain yet. Returns the links added.
        f"""CREATE FUNCTION {schema}.audit_seal() RETURNS bigint LANGUAGE plpgsql {settings}
            AS $$
            DECLARE
                head_seq bigint := 0;
                head_hash text := '{ZERO}';
                added bigint := 0;
                digest text;
                r record;
            BEGIN
                LOCK TABLE audit_chain IN SHARE ROW EXCLUSIVE MODE;
                SELECT chain_seq, link_hash INTO head_seq, head_hash FROM audit_chain
                    ORDER BY chain_seq DESC LIMIT 1;
                IF NOT FOUND THEN head_seq := 0; head_hash := '{ZERO}'; END IF;
                FOR r IN SELECT * FROM ({unsealed}) u ORDER BY u.at, u.tbl, u.id LOOP
                    head_seq := head_seq + 1;
                    digest := audit_digest(r.doc);
                    INSERT INTO audit_chain VALUES (head_seq, r.tbl, r.id, digest, head_hash,
                        audit_link(head_hash, head_seq, r.tbl, r.id, digest), now());
                    head_hash := audit_link(head_hash, head_seq, r.tbl, r.id, digest);
                    added := added + 1;
                END LOOP;
                RETURN added;
            END $$""",
        # Walk the chain: every link follows from the one before, and every linked row
        # still exists with the content it had when it was sealed.
        f"""CREATE FUNCTION {schema}.audit_verify() RETURNS TABLE (status text, links bigint,
            head_seq bigint, head_hash text, failed_seq bigint, problem text, unsealed bigint)
            LANGUAGE plpgsql STABLE {settings} AS $$
            DECLARE
                prev text := '{ZERO}';
                expected bigint := 1;
                link record;
                fault record;
            BEGIN
                status := 'ok'; links := 0; head_seq := 0; head_hash := '{ZERO}';
                SELECT count(*) INTO unsealed FROM ({unsealed}) u;
                FOR link IN SELECT * FROM audit_chain ORDER BY chain_seq LOOP
                    IF link.chain_seq <> expected THEN
                        problem := 'gap';
                    ELSIF link.prev_hash <> prev OR link.link_hash <> audit_link(
                            link.prev_hash, link.chain_seq, link.table_name, link.row_id,
                            link.row_digest) THEN
                        problem := 'link_broken';
                    END IF;
                    IF problem IS NOT NULL THEN
                        status := 'broken'; failed_seq := link.chain_seq;
                        RETURN NEXT; RETURN;
                    END IF;
                    prev := link.link_hash; expected := expected + 1;
                    links := links + 1; head_seq := link.chain_seq; head_hash := link.link_hash;
                END LOOP;
                SELECT * INTO fault FROM ({changed}) x ORDER BY x.chain_seq LIMIT 1;
                IF FOUND THEN
                    status := 'broken'; failed_seq := fault.chain_seq;
                    problem := CASE WHEN fault.missing THEN 'row_missing' ELSE 'row_changed' END;
                END IF;
                RETURN NEXT;
            END $$""",
    ]


def upgrade():
    for statement in _chain_sql(SCHEMA, TABLES, APP_ROLES):
        op.execute(statement)
    # Rows written before this migration are linked now, in time order.
    op.execute(f"SELECT {SCHEMA}.audit_seal()")


def downgrade():
    raise RuntimeError("Evaluation migrations are append-only; restore into a new database.")
