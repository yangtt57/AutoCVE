#!/usr/bin/env bash
# Shared by the macOS and Linux launchers. Never source .env files as shell code.

autocve_has_env() {
    [ -f "$1" ] || return 1
    awk -v key="$2" '
        { line = $0; sub(/^[ \t]*export[ \t]+/, "", line); equals = index(line, "=") }
        equals {
            name = substr(line, 1, equals - 1)
            gsub(/^[ \t]+|[ \t]+$/, "", name)
            if (name == key) found = 1
        }
        END { exit !found }
    ' "$1"
}

autocve_read_env() {
    local file="$1" key="$2"
    [ -f "$file" ] || return 0
    awk -v key="$key" '
        { sub(/\r$/, ""); line = $0; sub(/^[ \t]*export[ \t]+/, "", line) }
        {
            equals = index(line, "=")
            if (!equals) next
            name = substr(line, 1, equals - 1)
            gsub(/^[ \t]+|[ \t]+$/, "", name)
            if (name != key) next
            value = substr(line, equals + 1)
            gsub(/^[ \t]+|[ \t]+$/, "", value)
            quote = substr(value, 1, 1)
            if (quote == "\"" || quote == sprintf("%c", 39)) {
                value = substr(value, 2)
                closing = index(value, quote)
                if (closing) value = substr(value, 1, closing - 1)
            } else {
                sub(/[ \t]+#.*/, "", value)
            }
            found = value
        }
        END { printf "%s", found }
    ' "$file"
}

autocve_docker_host() {
    if [ -n "${DOCKER_CONTEXT:-}" ]; then
        docker context inspect "$DOCKER_CONTEXT" --format '{{.Endpoints.docker.Host}}'
    elif [ -n "${DOCKER_HOST:-}" ]; then
        printf '%s\n' "$DOCKER_HOST"
    else
        docker context inspect --format '{{.Endpoints.docker.Host}}'
    fi
}

autocve_docker_socket() {
    # Bind sources are resolved by the daemon. On macOS this is the VM socket,
    # not the client socket under ~/.colima or ~/.docker.
    if [ "$(uname -s)" = Linux ]; then
        local endpoint
        endpoint="$(autocve_docker_host)" || return
        case "$endpoint" in
            unix://*) printf '%s\n' "${endpoint#unix://}"; return ;;
        esac
    fi
    printf '%s\n' /var/run/docker.sock
}
