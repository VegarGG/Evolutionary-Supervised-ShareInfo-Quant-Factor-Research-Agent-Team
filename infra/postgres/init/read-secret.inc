# Sourced only by trusted PostgreSQL startup scripts. Never log credential values.
qfr_read_secret() {
    local secret_value
    if [[ ! -f "$1" ]] || ! secret_value="$(cat -- "$1" 2>/dev/null)"; then
        printf 'Cannot read PostgreSQL secret: %s\n' "${1##*/}" >&2
        return 1
    fi
    if [[ -z "$secret_value" ]]; then
        printf 'Empty PostgreSQL secret: %s\n' "${1##*/}" >&2
        return 1
    fi
    printf -v "$2" '%s' "$secret_value"
}
