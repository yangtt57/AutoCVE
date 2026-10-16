# 独立 Pi Docker 动态验证

此功能对漏洞管理中已有记录进行独立验证：Pi Agent 在 Docker 中获取源码、安装依赖、构建并启动目标，实际执行 PoC 或请求，最后提交带原始证据的结论。它独立于主审计流程，可用于一键 CVE 等原有流程产生的漏洞记录。源码发现 v2 的候选目前保存在独立账本中，不会自动进入这条验证链路。

## 运行结构

```text
AutoCVE backend
  └─ docker exec / put_archive / get_archive
      └─ pi-verifier：Pi Agent、模型配置、工具与会话
          └─ verifier-dind：专用 Docker daemon
              └─ 被测项目容器
```

后端通过宿主 Docker API 驱动常驻的 `autocve-pi-verifier`。Pi 的 `DOCKER_HOST` 指向专用 daemon，不挂载宿主 Docker socket；两个验证服务把同一工作卷挂载到 `/verifier/work`，使 Pi 写入的文件对 daemon 可见。Pi 会话单独保存，不复用宿主 `~/.pi`。

专用 daemon 把构建、镜像、卷与清理操作集中在验证环境，但使用 **privileged DinD**，不能视为虚拟机级隔离。网络可用于下载源码和依赖。应用层会校验证据结构与必要字段，这不等于独立证明 Agent 的所有叙述都准确，仍应核对原始输出。

## 配置与启动

先按 [README](../README.md) 准备主应用。在 `backend/.env` 中填好 `LLM_PROVIDER`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_BASE_URL`，再配置：

```dotenv
VERIFICATION_AGENT_ENABLED=true
# 替换为实际值，与验证容器使用的 provider / model 一致
VERIFICATION_AGENT_MODEL_PROVIDER=your-provider
VERIFICATION_AGENT_MODEL_ID=your-model-id
VERIFICATION_AGENT_MAX_CONCURRENCY=1
```

`your-*` 是占位符，不是可直接使用的模型。默认启动脚本读取 `LLM_*` 为验证容器配置模型，后端使用 `VERIFICATION_AGENT_MODEL_*` 选择同一模型；两组值必须对应。

若要用独立的验证模型，在根目录 `.env` 配置 `VERIFIER_MODEL_PROVIDER`、`VERIFIER_MODEL_ID`、`VERIFIER_MODEL_BASE_URL`、`VERIFIER_API_KEY`，并将后端的 provider/model 对齐。显式 shell 环境优先，其次为根目录 `.env`，然后是 `backend/.env`；未填写的模型设置回退到 `LLM_*`。界面修改主审计模型不会自动修改 Pi 的容器配置。当前容器适配 OpenAI Chat Completions 兼容协议。

```bash
./scripts/verify-stack.sh up -d --build
./scripts/verify-stack.sh ps
# Compose 部署：修改 backend/.env 后重新创建服务以加载配置
./scripts/compose.sh up -d backend agent-worker one-click-cve-worker
```

Compose 后端启动自动执行迁移。本机开发则运行 `./stop.sh` 后 `./start.sh` 重新加载配置和迁移；手动启动时可在 `backend` 执行 `uv run --locked alembic upgrade head`。

### 网络设置

默认直连，DNS 沿用 Docker 设置。按需在根目录 `.env` 配置：

| 配置 | 用途 |
| --- | --- |
| `VERIFIER_HTTP_PROXY` / `VERIFIER_HTTPS_PROXY` | 验证容器及 daemon 的可选运行时代理 |
| `VERIFIER_DNS` / `VERIFIER_DNS_FALLBACK` | 能从容器访问的 DNS；脚本自动加载 DNS overlay，也传给 DinD 子容器 |
| `VERIFIER_REGISTRY_MIRROR` | 可选 DinD 镜像源 |
| `AUTOCVE_BUILD_HTTP_PROXY` / `AUTOCVE_BUILD_HTTPS_PROXY` | 构建镜像时下载依赖使用的代理 |
| `NPM_REGISTRY` | 可选 npm 源 |

内部通信需要在 `VERIFIER_NO_PROXY` 保留 `verifier-dind`。Linux 的 `host.docker.internal` 通过 `host-gateway` 映射；只监听宿主 `127.0.0.1` 的代理无法经 Docker bridge 访问。更多平台细节见 [部署说明](LINUX_DEPLOYMENT.md)。

## 从界面使用

进入“漏洞管理”，对已有漏洞点击“动态验证”，或在报告弹窗切换到动态验证页签。界面提供：

- 排队、运行、暂停、完成或失败状态，以及历次验证记录。
- 验证环境、目标 commit、构建信息、复现步骤与实际影响。
- 命令的 stdout/stderr、退出码及原始 HTTP 交互。
- 证据产物及其 SHA-256、限制与未覆盖部分。
- 暂停/继续和 Markdown 报告导出。

后端必须启用功能且验证容器可用。同一漏洞已有 `pending`、`running` 或 `paused` 验证时不能重复启动。

## 判定与证据

| verdict | 含义 |
| --- | --- |
| `confirmed` | 本次运行复现成功，给出原始证据、复现步骤与实际影响 |
| `refuted` | 提供推翻原报告的理由，需结合证据判断 |
| `inconclusive` | 已尝试但无法得出结论，保留未知条件 |
| `unverifiable` | 源码、依赖、凭证或构建等条件使验证无法进行，不表示漏洞不存在 |

`contract.py` 检查必要字段：`confirmed` 必须包含原始命令输出或 HTTP body，以及非空复现步骤和影响；`refuted`、`unverifiable` 分别需要理由。超出证据预算时逐步裁剪，保留首条原始证据。

验证结果单独保存与导出，当前不会自动覆盖原报告状态、CVSS 或原审计的漏洞计数。

## 暂停、恢复与后端重启

暂停通过 Docker `pause` 冻结整个 Pi 容器；继续通过 `unpause` 恢复同一进程。该操作会影响同容器的所有验证任务，因此默认并发保持 **1**。DinD 内已经启动的被测容器不会随 Pi 一起冻结。

应用记录暂停时长，并从显示的运行耗时中扣除；容器的硬超时会预留 `VERIFICATION_AGENT_MAX_PAUSE_SECONDS`。超出预留时间仍可能被终止。暂停期间正在进行的模型 HTTP 连接可能失效，长时间暂停后不保证能无缝继续。

后端重启后，原进程内后台任务不再存在。启动恢复会检查工作区：已有合法 `EVIDENCE.json` 时保存结果；否则标记中断失败、解冻验证容器并按运行标签清理环境，避免记录永久停在运行中。

## API

以下请求需要登录 token，`API` 是后端地址。各接口执行所有权与访问权限校验。

| 方法与相对路径 | 用途 |
| --- | --- |
| `POST /api/v1/vulnerabilities/{id}/verification` | 启动一次验证 |
| `GET /api/v1/vulnerabilities/{id}/verification` | 最近一次验证及证据 |
| `GET /api/v1/vulnerabilities/{id}/verification/history` | 历史列表 |
| `POST /api/v1/vulnerabilities/{id}/verification/pause` | 暂停 |
| `POST /api/v1/vulnerabilities/{id}/verification/resume` | 继续 |
| `GET /api/v1/vulnerabilities/{id}/reports/verification` | 可读验证报告 |

```bash
curl -X POST "$API/api/v1/vulnerabilities/<id>/verification" -H "Authorization: Bearer <token>"
```

## 配置项

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `VERIFICATION_AGENT_ENABLED` | `false` | 后端功能开关 |
| `VERIFICATION_AGENT_MODEL_PROVIDER` | `deepseek` | 必须与容器模型配置的 provider 一致 |
| `VERIFICATION_AGENT_MODEL_ID` | 空 | 必填，与容器模型 ID 一致 |
| `VERIFICATION_AGENT_THINKING_LEVEL` | `max` | 传给 Pi 的 thinking 级别 |
| `VERIFICATION_AGENT_TIMEOUT_SECONDS` | `3600` | 单次验证预算，秒 |
| `VERIFICATION_AGENT_MAX_PAUSE_SECONDS` | `14400` | 硬超时预留的累计暂停时间，秒 |
| `VERIFICATION_AGENT_MAX_CONCURRENCY` | `1` | 并发验证数；暂停操作作用于整个 Pi 容器 |
| `VERIFICATION_AGENT_CONTAINER` | `autocve-pi-verifier` | 后端驱动的常驻容器名 |
| `VERIFICATION_AGENT_WORKDIR` | `/verifier/work` | 必须与 Pi / DinD 两边挂载点一致 |
| `VERIFICATION_AGENT_TOOLS` | `read,write,edit,bash,grep,find,ls` | Pi 工具范围 |
| `VERIFIER_AGENT_CPUS` / `VERIFIER_AGENT_MEMORY` | `4.0` / `8g` | Pi 容器资源上限 |

`VERIFIER_*` 是启动容器时的配置；`VERIFICATION_AGENT_*` 是后端配置，两者不能互相替代。

## 检查与停止

```bash
./scripts/verify-stack.sh ps
./scripts/verify-stack.sh logs --tail 100 pi-verifier verifier-dind
# 可选：真正调用一次模型，会产生 API 用量
./scripts/verify-stack.sh smoke
# 停止服务，保留证据和会话数据卷
./scripts/verify-stack.sh stop
```

`ps`、`logs`、`down`、`config`、`build` 不要求填写模型密钥。不要在普通停止命令中加 `down -v`，它会删除验证环境数据卷。

可选的管道冒烟脚本会调用真实模型、尝试获取一个不可用目标，并检查写工作区、Pi 执行、证据取回、契约校验与报告渲染。它用于链路检查，不验证漏洞检出能力；先配置相同的后端模型和 Docker context：

```bash
# 项目根目录；使用 Bash 加载共享函数
bash -c 'source scripts/lib/platform.sh; export DOCKER_HOST="$(autocve_docker_host)"; cd backend; uv run --locked python ../scripts/verification-pipeline-smoke.py'
```

默认单元回归不调用模型：

```bash
cd backend
uv run --locked pytest -q -o addopts='' tests/verification_agent
```

## 当前边界

本功能提供独立、手动触发的验证，不会向目标维护者发送报告或自动申请 CVE。提示词约束 Agent 只对指定验证环境操作；提示词本身不构成网络隔离。会话和模型配置保存在验证专用卷，部署者应把该卷视为含敏感信息的运行数据。

当前尚未提供一键 CVE 批量自动验证、通用项目环境配方库、运行中取消、报告状态同步和 CVSS 重算。依赖安装失败、私有组件或目标环境差异仍会导致 `unverifiable` 或 `inconclusive`。
