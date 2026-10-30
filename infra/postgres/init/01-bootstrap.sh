#!/bin/sh
set -eu
# Database/role creation is bootstrap only. Tables and triggers use Alembic.
psql --username "$POSTGRES_USER" --dbname postgres --set=ON_ERROR_STOP=1 \
  --set=registry_password="$REGISTRY_PASSWORD" --set=research_password="$RESEARCH_PASSWORD" \
  --set=eval_password="$EVAL_PASSWORD" --set=feedback_password="$FEEDBACK_PASSWORD" \
  --set=control_password="$CONTROL_PASSWORD" \
  --set=registry_migration_password="$REGISTRY_MIGRATION_PASSWORD" \
  --set=research_migration_password="$RESEARCH_MIGRATION_PASSWORD" \
  --set=eval_migration_password="$EVAL_MIGRATION_PASSWORD" \
  --set=control_migration_password="$CONTROL_MIGRATION_PASSWORD" \
  --file="${QFR_INIT_SQL:-/docker-entrypoint-initdb.d/bootstrap.sql.in}"
