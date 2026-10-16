#!/usr/bin/env bash
# Pi + dedicated Docker daemon, on Linux or macOS.
# Usage: scripts/verify-stack.sh up -d --build | ps | logs -f | down | smoke
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/lib/platform.sh"
ENV_FILE="${AUTOCVE_ENV_FILE:-$ROOT/backend/.env}"
COMPOSE_ENV_FILE="${AUTOCVE_COMPOSE_ENV_FILE:-$ROOT/.env}"
CONTAINER="autocve-pi-verifier"
action="${1:-up}"
if [ "$#" -gt 0 ]; then shift; fi

# Explicit shell values (including empty proxy values) win over configuration.
for key in VERIFIER_API_KEY VERIFIER_MODEL_PROVIDER VERIFIER_MODEL_ID VERIFIER_MODEL_BASE_URL \
           VERIFIER_HTTP_PROXY VERIFIER_HTTPS_PROXY VERIFIER_NO_PROXY \
           VERIFIER_DNS VERIFIER_DNS_FALLBACK VERIFIER_REGISTRY_MIRROR; do
    if [ "${!key+x}" != x ]; then
        if autocve_has_env "$COMPOSE_ENV_FILE" "$key"; then
            value="$(autocve_read_env "$COMPOSE_ENV_FILE" "$key")"
        else
            value="$(autocve_read_env "$ENV_FILE" "$key")"
        fi
        export "$key=$value"
    fi
done
export VERIFIER_API_KEY="${VERIFIER_API_KEY:-$(autocve_read_env "$ENV_FILE" LLM_API_KEY)}"
export VERIFIER_MODEL_PROVIDER="${VERIFIER_MODEL_PROVIDER:-$(autocve_read_env "$ENV_FILE" LLM_PROVIDER)}"
export VERIFIER_MODEL_PROVIDER="${VERIFIER_MODEL_PROVIDER:-deepseek}"
export VERIFIER_MODEL_ID="${VERIFIER_MODEL_ID:-$(autocve_read_env "$ENV_FILE" LLM_MODEL)}"

if [ -z "$VERIFIER_MODEL_BASE_URL" ]; then
    VERIFIER_MODEL_BASE_URL="$(autocve_read_env "$ENV_FILE" LLM_BASE_URL)"
    if [ -z "$VERIFIER_MODEL_BASE_URL" ]; then
        case "$VERIFIER_MODEL_PROVIDER" in
            deepseek) VERIFIER_MODEL_BASE_URL=https://api.deepseek.com/v1 ;;
            openai) VERIFIER_MODEL_BASE_URL=https://api.openai.com/v1 ;;
        esac
    fi
    # Preserve custom API paths such as /api/v4 or /openai/v1.
    VERIFIER_MODEL_BASE_URL="${VERIFIER_MODEL_BASE_URL%/}"
    case "${VERIFIER_MODEL_BASE_URL#*://}" in
        */*) ;;
        ?*) VERIFIER_MODEL_BASE_URL="$VERIFIER_MODEL_BASE_URL/v1" ;;
    esac
fi
export VERIFIER_MODEL_BASE_URL

case "$action" in
    up|run|create|start|restart|smoke)
        if [ -z "$VERIFIER_API_KEY" ] || [ -z "$VERIFIER_MODEL_ID" ] || [ -z "$VERIFIER_MODEL_BASE_URL" ]; then
            echo "验证配置不完整：请在 $ENV_FILE 配置 LLM_API_KEY / LLM_MODEL / LLM_BASE_URL，或设置 VERIFIER_* 覆盖值。" >&2
            exit 2
        fi
        ;;
esac

# Direct networking by default. Docker supplies DNS unless explicitly overridden.
export VERIFIER_HTTP_PROXY="${VERIFIER_HTTP_PROXY:-}"
export VERIFIER_HTTPS_PROXY="${VERIFIER_HTTPS_PROXY:-$VERIFIER_HTTP_PROXY}"
export VERIFIER_NO_PROXY="${VERIFIER_NO_PROXY:-localhost,127.0.0.1,::1,verifier-dind,host.docker.internal,.local}"
compose=(docker compose --project-directory "$ROOT")
if [ -f "$COMPOSE_ENV_FILE" ]; then compose+=(--env-file "$COMPOSE_ENV_FILE"); fi
compose+=(-f "$ROOT/docker-compose.verify.yml")
if [ -n "$VERIFIER_DNS" ]; then
    compose+=(-f "$ROOT/docker-compose.verify.dns.yml")
fi

if [ "$action" = smoke ]; then
    echo "检查 Pi、专用 Docker daemon，并调用一次模型（会产生 API 用量）"
    docker exec "$CONTAINER" sh -c 'node --version && pi --version && docker info --format "daemon {{.ServerVersion}}"'
    docker exec "$CONTAINER" sh -c 'cd /tmp && timeout 180 pi --print --no-session --thinking low "Reply with exactly one word: pong"'
else
    exec "${compose[@]}" "$action" "$@"
fi
