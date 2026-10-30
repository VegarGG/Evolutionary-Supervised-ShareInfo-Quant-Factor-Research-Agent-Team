"""Phase 0 foundation; domain tables are introduced in their assigned phases."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE FUNCTION reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'append-only table'; END; $$""")


def downgrade():
    raise RuntimeError("Foundation migrations are append-only; restore into a new database.")
