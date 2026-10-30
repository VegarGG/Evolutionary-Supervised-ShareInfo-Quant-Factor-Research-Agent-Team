"""Online-only migrations; connection secrets never enter configuration logs."""

from alembic import context

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Use the research migration function with a separate owner connection")
context.configure(connection=connection, version_table_schema="research", transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()
