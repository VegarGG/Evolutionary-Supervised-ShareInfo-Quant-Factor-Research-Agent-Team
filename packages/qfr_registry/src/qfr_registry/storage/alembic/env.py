"""Online registry migration environment; no credentials in Alembic configuration."""

from alembic import context

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Use registry migrations with a separately supplied owner connection")
context.configure(connection=connection, version_table_schema="registry", transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()
