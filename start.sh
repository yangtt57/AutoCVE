#!/usr/bin/env bash
# 在后台启动本地开发环境，可从任意目录执行。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
source "$ROOT/scripts/lib/platform.sh"
mkdir -p pids logs

for tool in docker uv node npm curl lsof; do
    command -v "$tool" >/dev/null || { echo "缺少命令：$tool"; exit 1; }
done

running() {
    local name="$1" expected="$2" pid command
    [ -f "pids/$name.pid" ] || return 1
    pid="$(cat "pids/$name.pid")"
    [[ "$pid" =~ ^[0-9]+$ ]] || return 1
    command="$(ps -p "$pid" -o command= 2>/dev/null)" || return 1
    [[ "$command" == *"$expected"* ]]
}

BACKEND="$ROOT/backend/.venv/bin/uvicorn app.main:app"
FRONTEND="$(command -v node) $ROOT/frontend/node_modules/vite/bin/vite.js"
for service in backend frontend; do
    if [ "$service" = backend ]; then port=8000; expected="$BACKEND"; else port=5173; expected="$FRONTEND"; fi
    if ! running "$service" "$expected" && lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
        echo "端口 $port 已被占用，请先关闭之前启动的 ${service}，再运行此脚本。"
        exit 1
    fi
done

if ! docker info >/dev/null 2>&1; then
    if [ "$(uname -s)" = Darwin ] && command -v colima >/dev/null && [[ "$(docker context show)" == colima* ]]; then
        colima start
    else
        echo "请先启动 Docker 后重试。"
        exit 1
    fi
fi
export DOCKER_HOST="$(autocve_docker_host)"
"$ROOT/scripts/compose.sh" up -d --wait db redis

if ! running backend "$BACKEND"; then
    (
        cd backend
        uv sync --locked
        uv run --locked alembic upgrade head
        nohup "$ROOT/backend/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port 8000 --no-access-log >"$ROOT/logs/backend.log" 2>&1 </dev/null &
        echo $! >"$ROOT/pids/backend.pid"
    )
fi
if ! running frontend "$FRONTEND"; then
    (
        cd frontend
        [ -d node_modules ] || npm ci --no-audit --no-fund
        nohup "$(command -v node)" "$ROOT/frontend/node_modules/vite/bin/vite.js" --host 127.0.0.1 --port 5173 --strictPort >"$ROOT/logs/frontend.log" 2>&1 </dev/null &
        echo $! >"$ROOT/pids/frontend.pid"
    )
fi

for attempt in {1..60}; do
    if running backend "$BACKEND" && running frontend "$FRONTEND" &&
       curl --noproxy '*' -fsS --max-time 2 http://127.0.0.1:8000/health >/dev/null 2>&1 &&
       curl --noproxy '*' -fsS --max-time 2 http://127.0.0.1:5173/ >/dev/null 2>&1; then
        echo "AutoCVE 已启动：http://localhost:5173"
        echo "日志：$ROOT/logs/backend.log 和 frontend.log"
        echo "关闭：$ROOT/stop.sh"
        exit 0
    fi
    sleep 1
done
echo "启动未就绪，请检查 logs/backend.log 和 logs/frontend.log；可运行 ./stop.sh 清理。"
exit 1
