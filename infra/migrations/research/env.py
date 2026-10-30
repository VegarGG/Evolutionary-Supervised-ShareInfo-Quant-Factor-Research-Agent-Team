import os

from alembic import context
from sqlalchemy import create_engine

name = context.config.get_main_option("database")
url = os.environ[f"{name.upper()}_MIGRATION_URL"]
with create_engine(url).connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
