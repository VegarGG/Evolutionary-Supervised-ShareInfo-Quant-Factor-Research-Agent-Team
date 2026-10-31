#!/bin/bash
# Nightly backups (PLAN Section 17.5), run by the backup service from the postgres:16
# image so pg_dump matches the server.
#
#   qfr-backup serve   after the nightly time (QFR_NIGHTLY_LOCAL, deployment.yaml's
#                      schedule.nightly_local) run today's backup once, then keep a
#                      heartbeat; a backup missed while the Mac slept runs on wake-up.
#   qfr-backup now     run today's backup immediately, replacing today's folder.
#   qfr-backup prune   apply the retention policy only.
#
# One backup writes backups/<local date>/ with a custom-format (compressed) pg_dump of
# each of the four databases, logs.tar.gz on the first backup of a month, SHA256SUMS and,
# last, COMPLETE. It is written to a hidden staging folder and renamed into place, so a
# dated folder is always complete. Then it mirrors the content-addressed snapshot
# volumes and the evaluation store into backups/snapshots/ (new and changed files only;
# nothing is deleted) and prunes dated folders to the newest QFR_BACKUP_DAILY_RETENTION
# plus the first backup of each of the newest QFR_BACKUP_MONTHLY_RETENTION months.
#
# Each database is dumped with its migration role, which owns every object in it; the
# service reaches postgres over control_net only and has no egress.
set -euo pipefail
shopt -s inherit_errexit
umask 027

BACKUPS=${QFR_BACKUPS_DIR:-/backups}
LOG_DIR=${QFR_LOG_DIR:-/var/log/qfr/backup}
LOG_VOLUME=${QFR_LOG_VOLUME:-/var/log/qfr}
MIRRORS=${QFR_MIRROR_SOURCES:-full=/mirror/full research=/mirror/research eval_store=/mirror/eval_store}
DATABASES=${QFR_BACKUP_DATABASES:-registry_db=REGISTRY_MIGRATION_URL research_db=RESEARCH_MIGRATION_URL eval_db=EVAL_MIGRATION_URL control_db=CONTROL_MIGRATION_URL}
HEARTBEAT=${QFR_HEARTBEAT_FILE:-/tmp/heartbeat}
POLL=${QFR_BACKUP_POLL_SECONDS:-60}
RETRY=${QFR_BACKUP_RETRY_SECONDS:-900}
DAY_PATTERN='^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
REQUEST_ID=""

new_request_id() { REQUEST_ID=$(cat /proc/sys/kernel/random/uuid); }

# One LogLine (qfr_core.contracts.LogLine) per call: level, event, outcome, payload JSON.
log() {
    local level=$1 event=$2 outcome=$3 payload=${4:-"{}"}
    local file
    mkdir -p "$LOG_DIR"
    file="$LOG_DIR/$(date -u +%F).jsonl"
    printf '{"event":"%s","level":"%s","outcome":"%s","payload":%s,"principal":"backup","request_id":"%s","service":"backup","ts":"%s","zone":"control"}\n' \
        "$event" "$level" "$outcome" "$payload" "${REQUEST_ID:-none}" \
        "$(date -u +%Y-%m-%dT%H:%M:%S.%6NZ)" >>"$file"
}

# "postgresql+psycopg://user:password@host:port/db" into PGUSER, PGPASSWORD, PGHOST, PGPORT.
# Generated passwords are URL-safe tokens, so no percent-decoding is needed.
connect_from() {
    local url=${!1:-}
    if [[ ! $url =~ ^postgresql(\+psycopg)?://([^:@/]+):([^@/]+)@([^:/]+):([0-9]+)/([A-Za-z0-9_]+)$ ]]; then
        echo "backup: $1 is not set or not a postgresql URL" >&2
        return 1
    fi
    if [[ ${BASH_REMATCH[6]} != "$2" ]]; then
        echo "backup: $1 names database ${BASH_REMATCH[6]}, not $2" >&2
        return 1
    fi
    export PGUSER=${BASH_REMATCH[2]} PGPASSWORD=${BASH_REMATCH[3]}
    export PGHOST=${BASH_REMATCH[4]} PGPORT=${BASH_REMATCH[5]}
}

complete_days() {
    local name
    for path in "$BACKUPS"/*/; do
        name=$(basename "$path")
        if [[ $name =~ $DAY_PATTERN ]] && [[ -f "$path/COMPLETE" ]]; then
            echo "$name"
        fi
    done | sort
}

# Copy files that are new or newer than the mirror's copy. Hidden staging files and the
# evaluation store's scratch folder are skipped; nothing in the mirror is ever deleted.
mirror() {
    local source=$1 target=$2 copied=0 relative destination
    [[ -d $source ]] || { echo 0; return 0; }
    mkdir -p "$target"
    while IFS= read -r -d '' file; do
        relative=${file#"$source"/}
        destination="$target/$relative"
        if [[ ! -e $destination || $file -nt $destination ]]; then
            mkdir -p "$(dirname "$destination")"
            cp --preserve=mode,timestamps "$file" "$(dirname "$destination")/.mirror.partial"
            mv -f "$(dirname "$destination")/.mirror.partial" "$destination"
            copied=$((copied + 1))
        fi
    done < <(find "$source" -path "$source/scratch" -prune -o -name '.*' -prune -o -type f -print0)
    echo "$copied"
}

prune() {
    local daily=${QFR_BACKUP_DAILY_RETENTION:?set from deployment.yaml}
    local monthly=${QFR_BACKUP_MONTHLY_RETENTION:?set from deployment.yaml}
    local -a days keep=() firsts=()
    local day month last_month="" removed=0
    mapfile -t days < <(complete_days)
    # The newest daily dumps.
    keep+=("${days[@]:$((${#days[@]} > daily ? ${#days[@]} - daily : 0))}")
    # The first dump of each month, newest months first.
    for day in "${days[@]}"; do
        month=${day:0:7}
        if [[ $month != "$last_month" ]]; then
            firsts+=("$day")
            last_month=$month
        fi
    done
    keep+=("${firsts[@]:$((${#firsts[@]} > monthly ? ${#firsts[@]} - monthly : 0))}")
    for day in "${days[@]}"; do
        if [[ " ${keep[*]} " != *" $day "* ]]; then
            rm -rf -- "${BACKUPS:?}/$day"
            removed=$((removed + 1))
        fi
    done
    echo "$removed"
}

run_backup() {
    local day=$1
    local staging="$BACKUPS/.$day.partial" target="$BACKUPS/$day"
    local started name variable month first=true mirrored="" size
    started=$(date +%s)
    log INFO backup_started ok "{\"day\":\"$day\"}"
    rm -rf -- "$staging"
    mkdir -p "$staging"
    for spec in $DATABASES; do
        name=${spec%%=*}
        variable=${spec#*=}
        connect_from "$variable" "$name"
        pg_dump --format=custom --compress=6 --no-password --dbname="$name" \
            --file="$staging/$name.dump"
    done
    month=${day:0:7}
    for other in $(complete_days); do
        if [[ ${other:0:7} == "$month" && $other != "$day" ]]; then first=false; fi
    done
    if [[ $first == true && -d $LOG_VOLUME ]]; then
        # Monthly only (Section 17.5). Files can grow while tar reads them: exit 1 is fine.
        tar --create --gzip --file="$staging/logs.tar.gz" --warning=no-file-changed \
            -C "$LOG_VOLUME" . || [[ $? -eq 1 ]]
    fi
    (cd "$staging" && sha256sum -- * >SHA256SUMS)
    date -u +%Y-%m-%dT%H:%M:%SZ >"$staging/COMPLETE"
    rm -rf -- "$target"
    mv -- "$staging" "$target"
    for spec in $MIRRORS; do
        mirrored+="\"${spec%%=*}\":$(mirror "${spec#*=}" "$BACKUPS/snapshots/${spec%%=*}"),"
    done
    size=$(du -sk "$target" | cut -f1)
    log INFO backup_completed ok "{\"day\":\"$day\",\"kib\":$size,\"logs_archived\":$first,\"mirrored\":{${mirrored%,}},\"pruned\":$(prune),\"seconds\":$(($(date +%s) - started))}"
}

due() {
    local at today
    today=$(date +%F)
    at=$(date -d "$today ${QFR_NIGHTLY_LOCAL:?set from deployment.yaml}" +%s)
    (($(date +%s) >= at)) && [[ ! -f "$BACKUPS/$today/COMPLETE" ]]
}

serve() {
    log INFO service_started ok "{\"nightly_local\":\"$QFR_NIGHTLY_LOCAL\"}"
    while true; do
        if due; then
            new_request_id
            run_backup "$(date +%F)" &
            local pid=$!
            while kill -0 "$pid" 2>/dev/null; do touch "$HEARTBEAT"; sleep 5; done
            if ! wait "$pid"; then
                log ERROR backup_failed failed "{\"retry_seconds\":$RETRY}"
                touch "$HEARTBEAT"
                sleep "$RETRY"
                continue
            fi
        fi
        touch "$HEARTBEAT"
        sleep "$POLL"
    done
}

new_request_id
case ${1:-serve} in
    serve) serve ;;
    now)
        # errexit is ignored inside a function called from a condition, so run it in a
        # subshell that turns errexit back on and read its status afterwards.
        set +e
        (
            set -e
            run_backup "$(date +%F)"
        )
        status=$?
        set -e
        if ((status != 0)); then
            log ERROR backup_failed failed "{\"exit_code\":$status}"
            exit "$status"
        fi
        cat "$BACKUPS/$(date +%F)/SHA256SUMS"
        ;;
    prune) echo "{\"pruned\":$(prune)}" ;;
    *) echo "usage: qfr-backup serve|now|prune" >&2; exit 2 ;;
esac
