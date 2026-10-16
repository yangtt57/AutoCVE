#!/usr/bin/env bash
# Source deployment, using the same Compose services on Linux and macOS.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/lib/platform.sh"
cd "$ROOT"
if [ -z "${AUTOCVE_DOCKER_SOCKET:-}" ]; then
    AUTOCVE_DOCKER_SOCKET="$(autocve_read_env "$ROOT/.env" AUTOCVE_DOCKER_SOCKET)"
    export AUTOCVE_DOCKER_SOCKET="${AUTOCVE_DOCKER_SOCKET:-$(autocve_docker_socket)}"
fi
exec docker compose -f "$ROOT/docker-compose.yml" "$@"
