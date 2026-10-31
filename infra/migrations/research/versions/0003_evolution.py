"""Phase 5 research_db: the evolutionary engine's state (PLAN Sections 12 and 16.2).

Population members gain where they came from, their expression, W0 or released
metrics, the fitness detail and the generation they joined; islands record their best fitness and
the generation it last improved; archive cells name the elite's island and
descriptors; programs record when their population was initialized. bandit_outcomes
holds one row per published child counted by an island's Thompson-sampling arm, so a
child is counted once and every update can be traced back to its report. It is
insert-only like the other records of what happened.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

ISLAND = "CHECK (island_key ~ '^I[1-6]$')"
SOURCES = "'program', 'seed', 'pool', 'parent_program', 'migrant'"


def upgrade():
    op.execute(f"""ALTER TABLE population_members
        ADD COLUMN source text NOT NULL DEFAULT 'program' CHECK (source IN ({SOURCES})),
        ADD COLUMN kind text NOT NULL DEFAULT 'factor' CHECK (kind IN ('factor', 'strategy')),
        ADD COLUMN expression text,
        ADD COLUMN analysis jsonb,
        ADD COLUMN expected_sign integer CHECK (expected_sign IN (-1, 1)),
        ADD COLUMN joined_seq integer NOT NULL DEFAULT 0 CHECK (joined_seq >= 0),
        ADD COLUMN metrics jsonb,
        ADD COLUMN fitness_detail jsonb,
        ADD COLUMN originality double precision,
        ADD COLUMN archived_reason text,
        ADD COLUMN created_at timestamptz""")
    op.execute(
        "CREATE UNIQUE INDEX population_members_version_uq ON population_members "
        "(program_id, island_key, version_id)"
    )
    op.execute(
        "CREATE INDEX population_members_status_idx ON population_members "
        "(program_id, island_key, status)"
    )
    op.execute("""ALTER TABLE islands
        ADD COLUMN best_fitness double precision,
        ADD COLUMN best_seq integer,
        ADD COLUMN paused_reason text,
        ADD COLUMN paused_seq integer""")
    op.execute("""ALTER TABLE archive_cells
        ADD COLUMN island_key text,
        ADD COLUMN descriptors jsonb""")
    op.execute("ALTER TABLE programs ADD COLUMN population_initialized_at timestamptz")
    op.execute(f"""CREATE TABLE bandit_outcomes (
        program_id uuid NOT NULL REFERENCES programs (program_id),
        version_id uuid NOT NULL,
        island_key text NOT NULL {ISLAND},
        generation_seq integer NOT NULL CHECK (generation_seq >= 0),
        success boolean NOT NULL,
        fitness double precision NOT NULL,
        threshold double precision NOT NULL,
        report_id uuid,
        counted_at timestamptz NOT NULL,
        PRIMARY KEY (program_id, version_id)
    )""")
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON bandit_outcomes FROM research_rw")
    op.execute("""CREATE TRIGGER bandit_outcomes_immutable BEFORE UPDATE OR DELETE
        ON bandit_outcomes FOR EACH ROW EXECUTE FUNCTION reject_mutation()""")
    op.execute("""CREATE TRIGGER bandit_outcomes_no_truncate BEFORE TRUNCATE ON bandit_outcomes
        FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation()""")


def downgrade():
    raise RuntimeError("Research migrations are append-only; restore into a new database.")
