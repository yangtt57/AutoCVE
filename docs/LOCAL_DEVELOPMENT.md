# 本地开发环境

本机开发将 FastAPI 和 Vite 运行在宿主上，PostgreSQL 15、Redis 7 和扫描/验证工具使用 Docker。服务器常驻部署请使用 [Linux / macOS Compose 部署](LINUX_DEPLOYMENT.md)。

## 准备依赖

需要 Git、Python 3.12、uv、Node.js 22.19+、npm、Docker 和 Compose 2.24+，以及 `curl`、`lsof`。先启动 Docker；macOS 可使用 Docker Desktop 或 Colima，Linux 使用 Docker Engine。

PDF 导出依赖 Pango 等系统库。macOS 使用 Homebrew 时可安装：

```bash
brew install pango
```

Debian / Ubuntu 的系统库安装命令见 [Linux 主机开发步骤](LINUX_DEPLOYMENT.md#linux-主机开发方式)。中文 PDF 还需要系统可用的中文字体；后端容器已包含 Noto CJK 字体。

从项目根目录准备配置与依赖（已有配置请保留）：

```bash
cp -n .env.example .env
cp -n backend/env.example backend/.env
cd backend
uv sync --locked --python 3.12
cd ../frontend
npm ci
cd ..
```

编辑 `.env` 的数据库密码和 `backend/.env` 的模型配置、随机 `SECRET_KEY`。本机开发的 `DATABASE_URL` 使用 `127.0.0.1` 和相同密码；若改变发布端口，`DATABASE_URL` / `REDIS_URL` 也应同步。保留默认 inline 任务执行模式。

先启动基础服务，再检查依赖：

```bash
./scripts/compose.sh up -d --wait db redis
./scripts/check-platform.sh --native
```

## 启动与停止

```bash
./start.sh
./stop.sh
```

`start.sh` 自动同步依赖、迁移数据库、启动基础服务，并将前后端放到后台运行；`stop.sh` 停止前后端，保留数据库服务与数据。前端为 `http://localhost:5173`，后端文档为 `http://localhost:8000/docs`。日志在 `logs/backend.log` 和 `logs/frontend.log`，进程记录在 `pids/`。

首次启动创建管理员演示账号 `demo@example.com` / `demo123`。本机开发服务默认仅监听回环地址；对外部署前修改演示账号密码。

需要前台热重载时，分别在两个终端运行：

```bash
# 终端 1，项目根目录
./scripts/compose.sh up -d db redis
./scripts/dev-backend.sh
```

```bash
# 终端 2，项目根目录
cd frontend
npm run dev -- --host 127.0.0.1
```

不要同时运行后台与前台启动方式占用相同端口。前台进程用 Ctrl+C 停止；数据库与 Redis 可用 `./scripts/compose.sh stop db redis` 停止，数据保留。远程开发可用 SSH 转发 5173 端口。

## 扫描与验证镜像

源码发现需要静态扫描镜像，旧审计工具使用独立沙箱：

```bash
./scripts/compose.sh build static-scanner sandbox
```

独立 Pi 验证需先按 [动态验证说明](DYNAMIC_VERIFICATION.md) 配置 `VERIFICATION_AGENT_*`，再运行 `./scripts/verify-stack.sh up -d --build`。这些镜像没有包含在前后端依赖安装中。

macOS 的项目快照目录应位于 Docker 已共享的路径。脚本自动使用当前 Docker context；容器路径和本机路径的区别见 [平台部署](LINUX_DEPLOYMENT.md)。

## 常用检查

```bash
python3 scripts/manage_audit_skills.py verify
python3 -m unittest discover -s scripts/tests -v
cd backend
uv run --locked pytest -q -o addopts='' tests/discovery tests/scan_runtime tests/triage_runtime tests/verification_agent
cd ../frontend
npm run type-check
npm run build
```

默认回归不调用真实模型；真实 Semgrep Docker 测试需要显式启用，Pi 的 `smoke` 会实际调用模型，见各功能文档。上游部分测试依赖特定环境，以上是本 fork 的定向检查，不等于全库测试全部通过。

后端以 `uv.lock` 为依赖基准；`requirements-lock.txt` 是其导出，`requirements.txt` 引用该锁文件以兼容 pip。不要把另一台机器的 `.venv` / `node_modules` 复制过来。真实配置、日志、缓存和生成的技能运行索引已被 Git 忽略。
