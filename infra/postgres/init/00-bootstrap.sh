#!/usr/bin/env bash
set -euo pipefail
set +x
source "${BASH_SOURCE[0]%/*}/read-secret.inc"
# Optional paths are for the isolated regression harness; Compose uses the defaults.
secret_dir=${1:-/run/qfr-postgres-secrets}
sql_file=${2:-/opt/qfr/bootstrap/init.sql}
trap 'rm -f -- "$secret_dir"/*' EXIT
pending="${PGDATA:?}/.qfr-bootstrap-pending"
touch "$pending"
qfr_read_secret "$secret_dir/registry_app_password" REGISTRY_PASSWORD
qfr_read_secret "$secret_dir/research_rw_password" RESEARCH_PASSWORD
qfr_read_secret "$secret_dir/eval_rw_password" EVAL_PASSWORD
qfr_read_secret "$secret_dir/feedback_ro_password" FEEDBACK_PASSWORD
# Pass credentials only to this SQL child after every read succeeds, never in argv.
REGISTRY_PASSWORD="$REGISTRY_PASSWORD" RESEARCH_PASSWORD="$RESEARCH_PASSWORD" \
EVAL_PASSWORD="$EVAL_PASSWORD" FEEDBACK_PASSWORD="$FEEDBACK_PASSWORD" \
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres -f "$sql_file"
rm -- "$pending"
