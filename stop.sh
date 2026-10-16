#!/usr/bin/env bash
# 停止本脚本启动的前后端与本项目数据库，保留数据。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

stop_service() {
    local name="$1" expected="$2" pid command
    if [ ! -f "pids/$name.pid" ]; then
        echo "$name 没有 PID 记录，跳过（手动启动的服务请在对应终端关闭）。"
        return
    fi
    pid="$(cat "pids/$name.pid")"
    if [[ "$pid" =~ ^[0-9]+$ ]]; then
        command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
        if [[ "$command" == *"$expected"* ]]; then
            kill -TERM "$pid" 2>/dev/null || true
            for attempt in {1..30}; do
                kill -0 "$pid" 2>/dev/null || break
                sleep 1
            done
            if kill -0 "$pid" 2>/dev/null; then
                echo "$name 尚未退出，保留 PID 记录；请检查日志后重试。"
                return 1
            fi
            echo "$name 已停止。"
        else
            echo "$name 进程已退出或 PID 已复用，不终止其他进程。"
        fi
    fi
    rm -f "pids/$name.pid"
}

stop_service frontend "$(command -v node) $ROOT/frontend/node_modules/vite/bin/vite.js"
stop_service backend "$ROOT/backend/.venv/bin/uvicorn app.main:app"
if docker info >/dev/null 2>&1; then
    "$ROOT/scripts/compose.sh" stop db redis
else
    echo "Docker 未运行，跳过容器停止。"
fi
echo "AutoCVE 已关闭，数据库数据已保留。"
