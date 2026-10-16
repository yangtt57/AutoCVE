#!/usr/bin/env bash
# Start the local API with the active Docker context (including Colima).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/lib/platform.sh"
cd "$ROOT/backend"
export DOCKER_HOST="$(autocve_docker_host)"
uv sync --locked
uv run --locked alembic upgrade head
exec uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --no-access-log
