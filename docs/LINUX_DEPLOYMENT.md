# Linux 与 macOS 部署

当前源码使用同一套 Compose 服务支持 Linux x86_64 / ARM64 和 macOS Docker 虚拟机。
Linux 建议采用 Docker Engine + Compose 插件部署；后端、前端、扫描器与 Pi 验证器均在 Linux 容器中运行。
本机开发仍可使用 `start.sh` / `stop.sh`。

## Linux 源码部署

准备 Docker Engine、Docker Compose 2.24 或以上版本、Git。当前 Pi 验证环境使用 privileged DinD，
部署说明按常规 rootful Docker Engine 编写；rootless Docker 的 socket 可以配置，但嵌套验证能力仍需在目标机器单独验证。

先克隆本 fork，再准备配置；已有仓库和配置文件请保留并按示例补充：

```bash
git clone https://github.com/yangtt57/AutoCVE.git
cd AutoCVE
cp -n .env.example .env
cp -n backend/env.example backend/.env
```

编辑配置：

- `.env`：服务端口、数据库密码和可选网络设置。新数据库建议用 `openssl rand -hex 24` 生成 `POSTGRES_PASSWORD`；已初始化的数据卷不会因为改环境变量自动修改数据库密码。
- `backend/.env`：填写 `LLM_API_KEY`、`LLM_MODEL`、`LLM_BASE_URL`、`LLM_PROVIDER` 和随机 `SECRET_KEY`。启用独立 Pi 验证时设置 `VERIFICATION_AGENT_ENABLED=true`，并填写与验证容器一致的 `VERIFICATION_AGENT_MODEL_ID` / `VERIFICATION_AGENT_MODEL_PROVIDER`。
- Compose 会为 API 和 worker 统一设置容器内数据库、Redis、存储和 Docker 地址，不应把 Mac 上 `/Users/...` 或 `/Volumes/...` 路径填入新服务器配置。

```bash
./scripts/check-platform.sh
./scripts/compose.sh build backend frontend sandbox static-scanner
./scripts/compose.sh up -d db redis backend agent-worker one-click-cve-worker frontend
# 可选：已配置独立 Pi 模型时启动
./scripts/verify-stack.sh up -d --build
./scripts/compose.sh ps
./scripts/verify-stack.sh ps
```

访问 `http://服务器地址:3000`。前端使用同源 `/api/v1` 访问后端，无需将前端 API 地址写成服务器 IP。
默认只有网页端口监听所有地址；API、PostgreSQL、Redis、Adminer 的宿主端口监听 `127.0.0.1`。
各端口和监听地址可在 `.env` 修改。主服务带 `unless-stopped` 重启策略。

当前源码新增的发现和验证能力应从源码构建；`docker-compose.prod*.yml` 指向已发布的 v1.0.5 镜像，不包含本 fork 的新增功能。

## Docker 路径与权限

`scripts/compose.sh` 自动选择 socket：Linux 使用当前 context 的 Unix socket，macOS 使用 Docker 虚拟机内的 `/var/run/docker.sock`。
特殊 Linux 安装可在 `.env` 设置 `AUTOCVE_DOCKER_SOCKET=/run/user/1000/docker.sock`。
运行脚本的账号应已具有对应 daemon 的访问权限；脚本不会自动修改 Docker 用户组或 socket 权限。

项目目录统一挂载到 `/workspace/projects`；持久化上传、源码快照和扫描结果保存在共享数据卷 `/app/uploads`。
API 与两个 worker 使用同一份数据，扫描器会将容器内路径转换成 Docker daemon 可见的真实挂载路径。
Pi 与专用 DinD 共享 `/verifier/work`，不依赖宿主的项目绝对路径，也不挂载宿主 Docker socket。

在服务器上使用本地目录项目时，可把源码放在仓库的 `projects/` 目录下，界面使用 `/workspace/projects/项目目录`。
从 Mac 迁移的数据库记录若包含旧本地目录路径，需要重新导入源码或更新项目路径；旧任务快照不能靠改配置自动搬迁。
不要直接复制 Mac 的 `.venv` 或 `node_modules`。已有审计数据迁移应同时备份数据库、上传卷、项目目录、Skills 和报告模板；首次部署步骤不会迁移旧数据。

远程 Docker context 的 bind mount 由远端 daemon 解析。请将源码仓库放在 Linux 服务器上执行部署脚本，
不要从 Mac 把未同步的本地目录直接挂给远程 daemon。

## 代理、DNS 与镜像源

共享配置默认直连、沿用 Docker 的 DNS。`verify-stack.sh` 不再依赖 macOS `scutil`，也不强制使用某个 Clash 端口、公网 DNS 或镜像站。
如确实需要，在服务器 `.env` 设置：

```dotenv
VERIFIER_HTTP_PROXY=http://host.docker.internal:7897
VERIFIER_HTTPS_PROXY=http://host.docker.internal:7897
VERIFIER_DNS=10.0.0.53
VERIFIER_DNS_FALLBACK=10.0.0.54
VERIFIER_REGISTRY_MIRROR=https://你的镜像源
```

这些值是示例，应换成目标网络的真实配置。`VERIFIER_HTTP_PROXY=` 表示不设置 HTTP 代理。
Linux 上 `host.docker.internal` 通过 `host-gateway` 映射到宿主；只监听宿主 `127.0.0.1` 的代理无法从 Docker bridge 访问。
DNS 也必须能从容器访问，不能直接照抄本机的 `127.0.0.53` stub resolver。
设置 `VERIFIER_DNS` 后，脚本自动追加 `docker-compose.verify.dns.yml`，同时配置验证容器和 DinD 子容器的 DNS。

`VERIFIER_*` 代理只负责验证环境运行时。构建依赖下载可设置 `AUTOCVE_BUILD_HTTP_PROXY` / `AUTOCVE_BUILD_HTTPS_PROXY`；
`NPM_REGISTRY` 可覆盖前端和 Pi 镜像的 npm 源。基础镜像的拉取仍由宿主 Docker daemon 的网络配置负责。
显式 `VERIFIER_MODEL_*` 可覆盖后端模型设置，已有 `/v1` 或自定义路径的 API 地址会被保留。

## Linux 主机开发方式

如果需要热重载而不把 API / 前端放进容器，准备 Python 3.12、uv、Node.js 22.19+、npm、Docker Compose。
Debian / Ubuntu 还需要系统库：

```bash
sudo apt-get update
sudo apt-get install -y git curl lsof build-essential pkg-config libpq-dev libffi-dev \
  libpango-1.0-0 libpangoft2-1.0-0 libpangocairo-1.0-0 libcairo2 \
  libgdk-pixbuf-2.0-0 fontconfig fonts-noto-cjk
cd backend
uv sync --locked --python 3.12
cd ../frontend
npm ci
cd ..
./scripts/check-platform.sh --native
./start.sh
```

本机模式 `backend/.env` 的数据库密码应与根目录 `.env` 一致，数据库地址使用 `127.0.0.1`，任务执行模式保持默认 inline。
若在 `.env` 改过数据库或 Redis 发布端口，也要同步修改 `DATABASE_URL` / `REDIS_URL`。
网页默认仅在 `127.0.0.1:5173` 提供开发服务，远程开发可使用 SSH 端口转发；服务器日常访问用上面的 Compose 部署。
静态扫描、旧沙箱与独立 Pi 验证的镜像仍需按需构建。

## 检查与维护

```bash
./scripts/check-platform.sh             # 只读检查，不调用模型
python3 -m unittest discover -s scripts/tests -v
./scripts/compose.sh logs --tail 100 backend agent-worker
./scripts/verify-stack.sh logs --tail 100 pi-verifier verifier-dind
```

需要验证模型连通时可显式运行 `./scripts/verify-stack.sh smoke`，这会真正调用一次 Pi 模型。
停止主服务用 `./scripts/compose.sh stop`，停止验证环境用 `./scripts/verify-stack.sh stop`，数据卷保留。
`ps`、`logs`、`down`、`config`、`build` 不要求模型密钥，便于排查未配置完成的机器。

平台回归覆盖 macOS / Linux 脚本、Compose 解析和 Linux 镜像构建；它不建立漏洞检测评测体系。
主机发行版的 Docker 内核能力、SELinux 和网络规则仍应通过目标机预检确认。

2026-10-17 本地验证：macOS 与 Linux ARM64 容器各通过 15 项平台测试，19 项后端相关回归通过；
后端、前端、DinD 镜像构建成功，全新 PostgreSQL 迁移、API `/health`、worker 导入、多语言解析、
中文 PDF 渲染、Nginx 配置和独立 DinD 启动均通过。测试使用临时容器和数据库，未触发模型审计或 PoC。
Linux x86_64 镜像构建已加入 GitHub Actions，但本轮未在物理 x86_64 服务器上执行。

参考：[Docker Compose 网络](https://docs.docker.com/compose/how-tos/networking/)、
[Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/)、
[uv Docker 部署](https://docs.astral.sh/uv/guides/integration/docker/)、
[Docker Engine 安装](https://docs.docker.com/engine/install/)。
