#!/bin/bash
# Nightly backups (PLAN Section 17.5), run by the backup service from the postgres:16
# image so pg_dump matches the server.
#
#   qfr-backup serve   after the nightly time (QFR_NIGHTLY_LOCAL, deployment.yaml's
#                      schedule.nightly_local) run today's backup once, then keep a
#                      heartbeat; a backup missed while the Mac slept runs on wake-up.
#   qfr-backup now     run today's backup immediately, replacing today's folder.
#   qfr-backup prune   apply the retention policy only.
#   qfr-backup verify  verify the retained backups only (also run after every backup).
#
# One backup writes backups/<local date>/ with a custom-format (compressed) pg_dump of
# each of the four databases, logs.tar.gz on the first backup of a month, SHA256SUMS and,
# last, COMPLETE. It is written to a hidden staging folder and renamed into place, so a
# dated folder is always complete. Then it mirrors the content-addressed snapshot
# volumes and the evaluation store into backups/snapshots/ (new and changed files only;
# nothing is deleted) and prunes dated folders to the newest QFR_BACKUP_DAILY_RETENTION
# plus the first backup of each of the newest QFR_BACKUP_MONTHLY_RETENTION months.
#
# Before a database with an audit hash chain (Phase 8, P8.5) is dumped, its chain is
# sealed and verified, and AUDIT_CHAINS.json records each chain's status and head, and
# whether it still holds the head the previous backup recorded (AUDIT_HEADS). After the
# backup, every retained folder's SHA256SUMS is checked again, the newest dumps are read
# back with pg_restore --list, and the result is written to backups/VERIFIED.json, which
# ops-nightly reads; a failure there raises the backup alert.
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
# The databases with an audit hash chain, and the schema that holds it.
AUDITED=${QFR_AUDIT_CHAINS:-registry_db=public eval_db=eval control_db=public}
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

audit_schema() {
    local spec
    for spec in $AUDITED; do
        if [[ ${spec%%=*} == "$1" ]]; then echo "${spec#*=}"; return 0; fi
    done
}

query() {
    psql --no-psqlrc --no-password --quiet -v ON_ERROR_STOP=1 --tuples-only --no-align \
        --field-separator=' ' --dbname="$1" -c "$2"
}

# Seal the database's chain, verify it, and check it still holds the previous backup's
# head. Prints one JSON object; returns 1 when the chain is broken. Needs connect_from.
audit_chain() {
    local name=$1 schema=$2 previous=$3 status="" links head_seq head_hash failed problem
    local unsealed extends=null prev_seq="" prev_hash="" found
    if ! query "$name" "SELECT $schema.audit_seal()" >/dev/null 2>&1; then
        echo '{"status":"unavailable"}'
        return 0
    fi
    read -r status links head_seq head_hash failed problem unsealed < <(query "$name" \
        "SELECT status, links, head_seq, head_hash, coalesce(failed_seq::text, '-'),
                coalesce(problem, '-'), unsealed FROM $schema.audit_verify()")
    if [[ -z ${status:-} ]]; then
        echo '{"status":"unavailable"}'
        return 0
    fi
    if [[ -n $previous && -f $previous/AUDIT_HEADS ]]; then
        read -r _ prev_seq prev_hash < <(grep "^$name " "$previous/AUDIT_HEADS" || true)
    fi
    if [[ -n $prev_seq && $prev_seq != 0 ]]; then
        found=$(query "$name" "SELECT link_hash FROM $schema.audit_chain WHERE chain_seq = $prev_seq")
        if [[ $found == "$prev_hash" ]]; then extends=true; else extends=false; fi
    fi
    printf '{"status":"%s","links":%s,"head_seq":%s,"head_hash":"%s","failed_seq":%s,"problem":%s,"unsealed":%s,"previous_head_seq":%s,"extends_previous":%s}' \
        "$status" "$links" "$head_seq" "$head_hash" \
        "$([[ $failed == - ]] && echo null || echo "$failed")" \
        "$([[ $problem == - ]] && echo null || echo "\"$problem\"")" "$unsealed" \
        "${prev_seq:-null}" "$extends"
    echo "$name $head_seq $head_hash" >>"$4"
    [[ $status == ok && $extends != false ]]
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
    local started name variable month first=true mirrored="" size schema chain chains=""
    local previous="" broken=false
    started=$(date +%s)
    log INFO backup_started ok "{\"day\":\"$day\"}"
    rm -rf -- "$staging"
    mkdir -p "$staging"
    previous=$(complete_days | grep -vx "$day" | tail -n 1 || true)
    [[ -n $previous ]] && previous="$BACKUPS/$previous"
    : >"$staging/AUDIT_HEADS"
    for spec in $DATABASES; do
        name=${spec%%=*}
        variable=${spec#*=}
        connect_from "$variable" "$name"
        schema=$(audit_schema "$name")
        if [[ -n $schema ]]; then
            if ! chain=$(audit_chain "$name" "$schema" "$previous" "$staging/AUDIT_HEADS"); then
                broken=true
                log ERROR audit_chain_broken failed "{\"database\":\"$name\",\"chain\":$chain}"
            fi
            chains+="\"$name\":$chain,"
        fi
        pg_dump --format=custom --compress=6 --no-password --dbname="$name" \
            --file="$staging/$name.dump"
    done
    printf '{%s}\n' "${chains%,}" >"$staging/AUDIT_CHAINS.json"
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
    log INFO backup_completed ok "{\"day\":\"$day\",\"kib\":$size,\"logs_archived\":$first,\"audit_chains_ok\":$([[ $broken == true ]] && echo false || echo true),\"mirrored\":{${mirrored%,}},\"pruned\":$(prune),\"seconds\":$(($(date +%s) - started))}"
    # A failed verification is recorded in VERIFIED.json and alerted by ops-nightly; the
    # backup itself is complete.
    verify || true
}

# Verify the retained backups (P8.5): every dated folder's SHA256SUMS still holds, the
# newest folder's dumps read back as archives, and its audit chains were intact. Writes
# backups/VERIFIED.json (replaced atomically); returns 1 when anything failed.
verify() {
    local -a days failures=()
    local day checked=0 newest="" dump status=PASS listed=0 audit=null item
    mapfile -t days < <(complete_days)
    for day in "${days[@]}"; do
        if [[ ! -f $BACKUPS/$day/SHA256SUMS ]] ||
            ! (cd "$BACKUPS/$day" && sha256sum --check --quiet --strict SHA256SUMS >/dev/null 2>&1); then
            failures+=("$day: checksums")
        fi
        checked=$((checked + 1))
    done
    if ((${#days[@]})); then
        newest=${days[-1]}
        for dump in "$BACKUPS/$newest"/*.dump; do
            [[ -e $dump ]] || continue
            if pg_restore --list "$dump" >/dev/null 2>&1; then
                listed=$((listed + 1))
            else
                failures+=("$newest: $(basename "$dump") unreadable")
            fi
        done
        if [[ -f $BACKUPS/$newest/AUDIT_CHAINS.json ]]; then
            audit=$(cat "$BACKUPS/$newest/AUDIT_CHAINS.json")
            if grep -q '"status":"broken"\|"extends_previous":false' <<<"$audit"; then
                failures+=("$newest: audit chain")
            fi
        fi
    else
        failures+=("no complete backup")
    fi
    ((${#failures[@]})) && status=FAIL
    local list=""
    for item in "${failures[@]}"; do list+="\"$item\","; done
    printf '{"status":"%s","at":"%s","newest":%s,"checked":%s,"archives_listed":%s,"failures":[%s],"audit_chains":%s}\n' \
        "$status" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        "$([[ -n $newest ]] && echo "\"$newest\"" || echo null)" "$checked" "$listed" \
        "${list%,}" "$audit" >"$BACKUPS/.VERIFIED.json.partial"
    mv -f -- "$BACKUPS/.VERIFIED.json.partial" "$BACKUPS/VERIFIED.json"
    if [[ $status == PASS ]]; then
        log INFO backup_verified ok "{\"checked\":$checked,\"archives_listed\":$listed}"
    else
        log ERROR backup_verification_failed failed "{\"failures\":[${list%,}]}"
        return 1
    fi
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
    verify)
        status=0
        verify || status=$?
        cat "$BACKUPS/VERIFIED.json"
        exit "$status"
        ;;
    *) echo "usage: qfr-backup serve|now|prune|verify" >&2; exit 2 ;;
esac
