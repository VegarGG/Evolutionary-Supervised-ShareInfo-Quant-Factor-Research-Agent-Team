"""Phase 8 registry_db (PLAN Section 7.6, P8.2): research notes are a third artifact kind.

A note is published like any version (family, version number, content hash) but has no
lineage edges and never enters a pool: the pool tables keep their factor and strategy
checks.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

KINDS = "'factor', 'strategy', 'research_note'"


def upgrade():
    for table in ("artifact_families", "artifact_versions"):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {table}_kind_check")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {table}_kind_check CHECK (kind IN ({KINDS}))"
        )


def downgrade():
    raise RuntimeError("Registry migrations are append-only; restore into a new database.")
