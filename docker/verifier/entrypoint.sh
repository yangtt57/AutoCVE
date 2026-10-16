#!/usr/bin/env bash
# 渲染 Pi 的配置（models.json / settings.json），然后移交 CMD。
#
# 设计要点：
#   - 模型通过环境变量注入，不往镜像里烤死任何模型名或密钥；
#   - 凭证只走环境变量（VERIFIER_API_KEY），容器内不落盘 auth.json；
#   - settings.json 显式写死工具白名单，避免依赖 Pi 的默认工具集。
set -euo pipefail

AGENT_DIR="${PI_CODING_AGENT_DIR:-/opt/pi/agent}"
WORKDIR_PATH="${VERIFIER_WORKDIR:-/verifier/work}"

PROVIDER_ID="${VERIFIER_MODEL_PROVIDER:-deepseek}"
MODEL_ID="${VERIFIER_MODEL_ID:-}"
BASE_URL="${VERIFIER_MODEL_BASE_URL:-https://api.deepseek.com/v1}"
API_KEY="${VERIFIER_API_KEY:-${DEEPSEEK_API_KEY:-${LLM_API_KEY:-}}}"

if [ -z "${MODEL_ID}" ]; then
  echo "VERIFIER_MODEL_ID is not set. Set it in .env (for example VERIFIER_MODEL_ID=deepseek-flash)." >&2
  exit 2
fi
if [ -z "${API_KEY}" ]; then
  echo "VERIFIER_API_KEY (or DEEPSEEK_API_KEY / LLM_API_KEY) is not set. The verifier cannot call the model without it." >&2
  exit 2
fi

mkdir -p "${AGENT_DIR}" "${AGENT_DIR}/sessions" "${WORKDIR_PATH}"

export VERIFIER_RENDER_PROVIDER_ID="${PROVIDER_ID}"
export VERIFIER_RENDER_MODEL_ID="${MODEL_ID}"
export VERIFIER_RENDER_BASE_URL="${BASE_URL}"
export VERIFIER_RENDER_API_KEY="${API_KEY}"

# 用 node 渲染 JSON，避免在 shell 里手工拼 JSON 处理转义。
node <<'NODE'
const fs = require("fs");
const path = require("path");

const agentDir = process.env.PI_CODING_AGENT_DIR || "/opt/pi/agent";

const models = {
  $schema: "https://pi.dev/schemas/models.schema.json",
  providers: {
    [process.env.VERIFIER_RENDER_PROVIDER_ID]: {
      baseUrl: process.env.VERIFIER_RENDER_BASE_URL,
      api: "openai-completions",
      apiKey: process.env.VERIFIER_RENDER_API_KEY,
      models: [{ id: process.env.VERIFIER_RENDER_MODEL_ID }],
    },
  },
};
fs.writeFileSync(path.join(agentDir, "models.json"), JSON.stringify(models, null, 2) + "\n");

const settings = {
  // 显式白名单：读/写/改/执行 + 检索。不接受扩展、MCP、skills、上下文文件。
  defaultTools: ["read", "write", "edit", "bash", "grep", "find", "ls"],
  quietStartup: true,
};
fs.writeFileSync(path.join(agentDir, "settings.json"), JSON.stringify(settings, null, 2) + "\n");
NODE

echo "[verifier] model=${PROVIDER_ID}/${MODEL_ID} baseUrl=${BASE_URL}"
echo "[verifier] agent dir=${AGENT_DIR} workdir=${WORKDIR_PATH}"
if [ -n "${DOCKER_HOST:-}" ]; then
  echo "[verifier] docker host=${DOCKER_HOST}"
fi

exec "$@"
