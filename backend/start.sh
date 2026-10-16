#!/bin/bash
# 使用 uv 启动后端服务

set -euo pipefail
cd "$(dirname "$0")"

echo "🚀 启动 AutoCVE 后端服务..."

# 检查 uv 是否安装
if ! command -v uv &> /dev/null; then
    echo "❌ 未找到 uv，请先安装："
    echo "   curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

exec bash ../scripts/dev-backend.sh

