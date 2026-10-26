#!/usr/bin/env bash
set -euo pipefail
# Secret values enter psql through environment, never CLI arguments or logs.
export REGISTRY_PASSWORD="$(cat /run/secrets/registry_app_password)"
export RESEARCH_PASSWORD="$(cat /run/secrets/research_rw_password)"
export EVAL_PASSWORD="$(cat /run/secrets/eval_rw_password)"
export FEEDBACK_PASSWORD="$(cat /run/secrets/feedback_ro_password)"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres -f /opt/qfr/init.sql
