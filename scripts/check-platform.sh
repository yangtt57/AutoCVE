#!/usr/bin/env bash
# Read-only preflight. Does not launch tasks, containers or model requests.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/lib/platform.sh"
echo "平台：$(uname -s) / $(uname -m)"
case "$(uname -s)/$(uname -m)" in
    Linux/x86_64|Linux/aarch64|Linux/arm64|Darwin/x86_64|Darwin/arm64) ;;
    *) echo '当前部署脚本面向 Linux/macOS 的 x86_64 与 ARM64。' >&2; exit 1 ;;
esac
command -v docker >/dev/null || { echo '请先安装 Docker 和 Compose 插件。' >&2; exit 1; }
docker compose version
docker info --format 'Docker 服务端：{{.OSType}}/{{.Architecture}}'
"$ROOT/scripts/compose.sh" config --quiet
"$ROOT/scripts/verify-stack.sh" config --quiet
echo '主服务与验证服务的 Compose 配置有效。'
for image in autocve-static-scanner:latest autocve-sandbox:latest autocve-pi-verifier:latest autocve-verifier-dind:latest; do
    if docker image inspect "$image" >/dev/null 2>&1; then
        echo "镜像已就绪：$image"
    else
        echo "尚需构建：$image"
    fi
done
if [ "${1:-}" = --native ]; then
    for tool in uv node npm curl lsof; do
        command -v "$tool" >/dev/null || { echo "本机运行缺少命令：$tool" >&2; exit 1; }
    done
    echo "后端 Docker 地址：$(autocve_docker_host)"
    echo "uv：$(uv --version)；Node：$(node --version)"
    if [ -x "$ROOT/backend/.venv/bin/python" ]; then
        "$ROOT/backend/.venv/bin/python" -c 'import ijson; from tree_sitter_language_pack import get_language; get_language("java"); from weasyprint import HTML; HTML(string="<p>AutoCVE</p>").write_pdf()'
        echo 'Python 解析器、流式 JSON 读取与 PDF 渲染通过。'
    else
        echo '尚需在 backend 中执行 uv sync --locked --python 3.12。'
    fi
fi
