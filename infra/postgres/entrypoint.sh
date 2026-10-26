#!/usr/bin/env bash
# Trusted root startup only; application containers never run this wrapper.
set -euo pipefail
set +x
if [[ "${1:-}" == -* ]]; then set -- postgres "$@"; fi
if [[ "${1:-}" != postgres ]]; then
    exec /usr/local/bin/docker-entrypoint.sh "$@"
fi
for arg in "$@"; do
    case "$arg" in -'?'|--help|--describe-config|-V|--version)
        exec /usr/local/bin/docker-entrypoint.sh "$@" ;;
    esac
done
if [[ "$(id -u)" != 0 ]]; then
    printf '%s\n' 'PostgreSQL credential staging requires trusted root startup.' >&2
    exit 1
fi

secret_dir=/run/qfr-postgres-secrets
if [[ ! -d "$secret_dir" || "$(stat -f -c %T "$secret_dir")" != tmpfs ]]; then
    printf '%s\n' 'PostgreSQL credential staging requires its private tmpfs mount.' >&2
    exit 1
fi
umask 077
trap 'rm -f -- "$secret_dir"/*' EXIT
if [[ -e "${PGDATA:?}/.qfr-bootstrap-pending" ]]; then
    printf '%s\n' 'Incomplete QFR database bootstrap; operator recovery required.' >&2
    exit 1
fi
source /opt/qfr/postgres/init/read-secret.inc
# Validate every source before starting initdb. Assignment failures must propagate;
# an export builtin would mask a failed command substitution.
for role in postgres registry_app research_rw eval_rw feedback_ro; do
    qfr_read_secret "/run/secrets/${role}_password" credential
    if [[ "$role" != postgres ]]; then
        printf '%s' "$credential" > "$secret_dir/${role}_password"
        chown postgres:postgres "$secret_dir/${role}_password"
        chmod 0400 "$secret_dir/${role}_password"
    fi
    unset credential
done
chown postgres:postgres "$secret_dir"
chmod 0700 "$secret_dir"

# Public initialization assets may also be host-private in managed checkouts.
# Copy them inside the container; never change host file or secret permissions.
install -d -m 0755 /docker-entrypoint-initdb.d /opt/qfr/bootstrap
install -m 0755 /opt/qfr/postgres/init/00-bootstrap.sh /docker-entrypoint-initdb.d/00-bootstrap.sh
install -m 0644 /opt/qfr/postgres/init/read-secret.inc /docker-entrypoint-initdb.d/read-secret.inc
install -m 0644 /opt/qfr/postgres/init.sql /opt/qfr/bootstrap/init.sql
if [[ -s "$PGDATA/PG_VERSION" ]]; then
    # Existing databases are not reinitialized or given new passwords on restart.
    rm -f -- "$secret_dir"/*
fi
exec /usr/local/bin/docker-entrypoint.sh "$@"
