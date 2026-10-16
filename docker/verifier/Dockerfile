# AutoCVE 独立动态验证 Agent（Pi）镜像。
#
# 这个镜像故意不复用 autocve-sandbox：
#   - 它内置一个自主编码 Agent（Pi），位于 AutoCVE 的运行时之外，模型和会话都独立；
#   - 它允许随时安装工具链（这正是能真正把项目跑起来的前提）；
#   - 它是唯一有权调用 Docker API 的组件，并且只连接专用的 DinD daemon，
#     永远不挂宿主机的 /var/run/docker.sock。
#
# 构建：
#   docker compose -f docker-compose.verify.yml build
FROM node:22.19-bookworm

# Pi 要求 Node >= 22.19，基础镜像必须满足，否则 npm 安装会直接失败。
ARG PI_VERSION=1.2.0
ARG NPM_REGISTRY=https://registry.npmjs.org

# Pi 硬要求 Node >= 22.19。这里显式断言一次，避免基础镜像被改回旧版本后
# 在 npm install 阶段报一个看不懂的错误。
RUN node -e "const [major, minor] = process.versions.node.split('.').map(Number); if (major < 22 || (major === 22 && minor < 19)) { console.error('Pi requires Node >= 22.19, base image has ' + process.versions.node); process.exit(1); }"

RUN npm config set registry "${NPM_REGISTRY}" \
 && npm install -g --ignore-scripts "@earendil-works/pi-coding-agent@${PI_VERSION}" \
 && pi --version

# 基础工具链。验证 Agent 可以在运行时继续装东西（apt/pip/npm/go），
# 所以这里只放一套“大概率用得上”的底座，不追求覆盖所有生态。
RUN apt-get update && apt-get install -y --no-install-recommends \
      tini ca-certificates curl git jq unzip zip less procps \
      build-essential pkg-config \
      python3 python3-pip python3-venv \
      php-cli php-mbstring php-curl php-xml php-sqlite3 \
      golang-go default-jdk-headless \
      sqlite3 netcat-openbsd iproute2 dnsutils \
 && rm -rf /var/lib/apt/lists/*

# 去掉 PEP 668 的 EXTERNALLY-MANAGED 标记。
# 验证 Agent 会直接 `pip3 install ...` 装依赖，默认会被这个标记拦住；
# 这是个一次性的一次性容器，不需要 "受管控的 Python 环境" 那套保护。
RUN rm -f /usr/lib/python3*/EXTERNALLY-MANAGED

# Docker CLI + compose 插件。用官方 apt 源而不是 GitHub release 直链，
# 这样 arm64/amd64 都能装，也不依赖猜某个具体版本号。
ARG DEBIAN_CODENAME=bookworm
ARG DOCKER_APT_MIRROR=download.docker.com
RUN set -eux; \
    apt-get update; \
    install -m 0755 -d /etc/apt/keyrings; \
    curl -fsSL "https://${DOCKER_APT_MIRROR}/linux/debian/gpg" -o /etc/apt/keyrings/docker.asc; \
    chmod a+r /etc/apt/keyrings/docker.asc; \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://${DOCKER_APT_MIRROR}/linux/debian ${DEBIAN_CODENAME} stable" \
      > /etc/apt/sources.list.d/docker.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin; \
    rm -rf /var/lib/apt/lists/*; \
    docker --version; \
    docker compose version

# Agent 的配置目录与会话目录都留在容器内的独立位置，
# 不挂载宿主的 ~/.pi，避免和本机使用的 Pi 互相污染。
ENV PI_CODING_AGENT_DIR=/opt/pi/agent \
    PI_TELEMETRY=0 \
    PI_SKIP_VERSION_CHECK=1 \
    VERIFIER_WORKDIR=/verifier/work \
    VERIFIER_RULES=/opt/verifier/verifier-rules.md \
    NODE_OPTIONS=--max-old-space-size=2048

WORKDIR /verifier

COPY entrypoint.sh /opt/verifier/entrypoint.sh
COPY verifier-rules.md /opt/verifier/verifier-rules.md
RUN chmod 0755 /opt/verifier/entrypoint.sh

ENTRYPOINT ["/usr/bin/tini", "--", "/opt/verifier/entrypoint.sh"]
# 常驻容器：后端通过 docker exec 按需驱动一次验证。
# 常驻的意义是 Agent 装的工具链可以在多次验证之间复用。
CMD ["sleep", "infinity"]
