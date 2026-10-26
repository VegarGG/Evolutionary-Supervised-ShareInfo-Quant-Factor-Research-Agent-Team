"""Online-only migrations: credentials never enter Alembic config or logs."""

from alembic import context

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Use the evaluator migration command with an owner connection")
context.configure(connection=connection, version_table_schema="eval", transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()
