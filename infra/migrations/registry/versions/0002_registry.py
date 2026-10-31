"""Phase 2 registry_db (PLAN Section 16.1): artifacts, lineage, pools and the audit.

Every table is insert-only. registry_app holds SELECT and INSERT only (default
privileges from the bootstrap), and triggers reject UPDATE, DELETE and TRUNCATE for
every role, including the migration owner (REG-01).
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

HEX64 = "'^[a-f0-9]{64}$'"
SLUG = "'^[a-z0-9][a-z0-9_-]*$'"
TABLES = (
    "artifact_families",
    "artifact_versions",
    "artifact_parents",
    "pool_entries",
    "pool_events",
    "registry_events",
)


def upgrade():
    op.execute(f"""CREATE TABLE artifact_families (
        family_id uuid PRIMARY KEY,
        kind text NOT NULL CHECK (kind IN ('factor', 'strategy')),
        program_id uuid,
        job_id uuid,
        name text NOT NULL CHECK (name ~ {SLUG} AND length(name) <= 64),
        created_at timestamptz NOT NULL,
        created_by text NOT NULL,
        request_id text NOT NULL,
        -- A name is unique within the program (setup imports share the null program).
        UNIQUE NULLS NOT DISTINCT (kind, program_id, name)
    )""")

    op.execute(f"""CREATE TABLE artifact_versions (
        version_id uuid PRIMARY KEY,
        family_id uuid NOT NULL REFERENCES artifact_families (family_id),
        version_no integer NOT NULL CHECK (version_no >= 1),
        kind text NOT NULL CHECK (kind IN ('factor', 'strategy')),
        manifest jsonb NOT NULL,
        payload_text text NOT NULL,
        content_hash text NOT NULL UNIQUE CHECK (content_hash ~ {HEX64}),
        canonical_hash text NOT NULL CHECK (canonical_hash ~ {HEX64}),
        published_seq bigserial UNIQUE,
        published_at timestamptz NOT NULL,
        publisher text NOT NULL,
        publish_key text NOT NULL,
        analysis jsonb NOT NULL,
        request_id text NOT NULL,
        UNIQUE (family_id, version_no),
        UNIQUE (publisher, publish_key)
    )""")
    op.execute("CREATE INDEX artifact_versions_canonical_idx ON artifact_versions (canonical_hash)")

    op.execute("""CREATE TABLE artifact_parents (
        version_id uuid NOT NULL REFERENCES artifact_versions (version_id),
        parent_version_id uuid NOT NULL REFERENCES artifact_versions (version_id),
        relation text NOT NULL CHECK (relation IN ('parent', 'component')),
        ast_diff jsonb,
        PRIMARY KEY (version_id, parent_version_id),
        CHECK (version_id <> parent_version_id)
    )""")
    op.execute("CREATE INDEX artifact_parents_parent_idx ON artifact_parents (parent_version_id)")

    op.execute("""CREATE TABLE pool_entries (
        entry_id uuid PRIMARY KEY,
        pool text NOT NULL CHECK (pool IN ('factor', 'strategy')),
        version_id uuid NOT NULL REFERENCES artifact_versions (version_id),
        title text NOT NULL CHECK (length(title) BETWEEN 1 AND 120),
        created_at timestamptz NOT NULL,
        created_by text NOT NULL,
        approval_id uuid,
        setup_ref uuid,
        request_id text NOT NULL,
        UNIQUE (pool, version_id),
        -- An entry is authorized by exactly one of an approval or a setup import.
        CHECK ((approval_id IS NULL) <> (setup_ref IS NULL))
    )""")

    op.execute("""CREATE TABLE pool_events (
        event_id uuid PRIMARY KEY,
        event_seq bigserial UNIQUE,
        entry_id uuid NOT NULL REFERENCES pool_entries (entry_id),
        at timestamptz NOT NULL,
        principal text NOT NULL,
        action text NOT NULL CHECK (action IN ('ADDED', 'STATUS_CHANGED', 'ANNOTATED')),
        from_status text CHECK (from_status IN ('seed', 'approved', 'retired')),
        to_status text CHECK (to_status IN ('seed', 'approved', 'retired')),
        approved_tier text CHECK (approved_tier IN ('w1_pass', 'w2_pass', 'advanced', 'incubated')),
        approval_id uuid,
        setup_ref uuid,
        tags text[] NOT NULL DEFAULT '{}',
        note text CHECK (length(note) BETWEEN 1 AND 2000),
        request_id text NOT NULL,
        CHECK (COALESCE(to_status = 'approved', false) = (approved_tier IS NOT NULL)),
        CHECK (action <> 'ADDED' OR (
            from_status IS NULL AND (
                (to_status = 'seed' AND setup_ref IS NOT NULL AND approval_id IS NULL)
                OR (to_status = 'approved' AND approval_id IS NOT NULL AND setup_ref IS NULL)))),
        CHECK (action <> 'STATUS_CHANGED' OR (
            from_status IS NOT NULL AND to_status IN ('approved', 'retired')
            AND approval_id IS NOT NULL AND setup_ref IS NULL)),
        CHECK (action <> 'ANNOTATED' OR (
            from_status IS NULL AND to_status IS NULL AND approval_id IS NULL
            AND setup_ref IS NULL))
    )""")
    op.execute("CREATE INDEX pool_events_entry_idx ON pool_events (entry_id, event_seq)")

    op.execute("""CREATE TABLE registry_events (
        event_id uuid PRIMARY KEY,
        at timestamptz NOT NULL,
        principal text NOT NULL,
        action text NOT NULL,
        version_id uuid,
        entry_id uuid,
        request_id text NOT NULL,
        payload jsonb NOT NULL
    )""")
    op.execute("CREATE INDEX registry_events_request_idx ON registry_events (request_id)")

    # The current status is the latest status-bearing event; tags accumulate.
    op.execute("""CREATE VIEW pool_current_v AS
        SELECT e.entry_id, e.pool, e.version_id, s.to_status AS status, s.approved_tier,
               s.approval_id, e.setup_ref, e.title, e.created_at, e.created_by,
               COALESCE(t.tags, '{}'::text[]) AS tags, l.last_event_at
        FROM pool_entries e
        JOIN LATERAL (
            SELECT to_status, approved_tier, approval_id FROM pool_events
            WHERE entry_id = e.entry_id AND to_status IS NOT NULL
            ORDER BY event_seq DESC LIMIT 1
        ) s ON true
        JOIN LATERAL (
            SELECT max(at) AS last_event_at FROM pool_events WHERE entry_id = e.entry_id
        ) l ON true
        LEFT JOIN LATERAL (
            SELECT array_agg(DISTINCT tag ORDER BY tag) AS tags
            FROM pool_events pe CROSS JOIN LATERAL unnest(pe.tags) AS tag
            WHERE pe.entry_id = e.entry_id
        ) t ON true""")

    for table in TABLES:
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM registry_app")
        op.execute(f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_mutation()""")
        op.execute(f"""CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation()""")
    op.execute("REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON pool_current_v FROM registry_app")


def downgrade():
    raise RuntimeError("Registry migrations are append-only; restore into a new database.")
