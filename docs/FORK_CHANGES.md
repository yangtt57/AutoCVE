# 本 fork 的改动与来源

维护仓库：[yangtt57/AutoCVE](https://github.com/yangtt57/AutoCVE)。
基于：[larlarua/AutoCVE](https://github.com/larlarua/AutoCVE)。
初始源码基线：[`b26025f27199ba2d93145e4a08fc9015e8d846e4`](https://github.com/larlarua/AutoCVE/commit/b26025f27199ba2d93145e4a08fc9015e8d846e4)。
本次整理日期：2026-10-17。

项目、用户、工作流、模型设置、Agent 编排、原有审计模式、一键 CVE、漏洞管理、报告与基础 Skills 体系来自上游。本 fork 保留这些基础功能，在其上扩展源码发现、证据保存、独立动态验证和部署体验。上游公开的 CVE 列表不作为本 fork 的实验结果。

## 1. 源码发现与持久化账本

新增 `discovery_v2` 路径，复用现有模型与 Finding runtime：

- 建立不可变源码快照，保存版本、内容哈希、审计范围和排除项。
- 源码独立分析与 Semgrep 扫描并行；首轮结果冻结后再将工具告警反馈给模型，进行源码研判与定向补查。
- 原始扫描结果单独保存，以流式方式完整索引可解析的 occurrence。重复告警保留独立 ID，关联指纹只用于调度，不删除原始记录。
- 候选记录静态支持、未决和排除状态；每次修改追加版本，保留支持证据、反证与尚未确认的条件。
- 工作包使用租约、尝试 ID、逐项回执和检查点；预算用尽时保留已有结果与剩余工作，可在同一快照继续处理。
- 提供游标分页、原始产物下载、JSONL 导出与任务所有权校验。

旧扫描路径也取消首 200 条结果截断；旧 Triage/Finding 路径达到预算上限后保留已经完成的结构化结果，避免汇总覆盖中间成果。

主要代码：`backend/app/services/discovery/`、`backend/app/models/discovery.py`、`backend/app/api/v1/endpoints/discovery.py`、`backend/app/services/scan_runtime/`、`backend/app/services/agent/agents/orchestrator.py`。用法与 API 见 [源码发现说明](DISCOVERY_V2.md)。

## 2. 多语言、入口与信任边界

补充 tree-sitter 语法导航，覆盖 Java、Go、C#、PHP、Ruby、Rust、Kotlin、Swift、C/C++，并增强 Python、JavaScript、TypeScript 的索引与入口识别。

| 语言/场景 | 增加的导航线索示例 |
| --- | --- |
| Java / Kotlin | Spring MVC、JAX-RS、Servlet、Ktor 路由与处理函数 |
| Go | net/http、Gin、Echo、Fiber 的注册点与处理函数 |
| C# | ASP.NET 控制器与 Minimal API |
| PHP / Ruby | Laravel、Symfony、Rails、Sinatra 的路由与处理逻辑 |
| Rust / Swift | Axum、Actix、Vapor 的入口线索 |
| Python / JS / TS | Web 路由、命令、任务注册及导出符号；补充 NestJS/Express 等注册形式 |
| C / C++ 与公共库 | 函数、类型、导入、调用表达式与库入口导航 |

这些是源码定位与工作规划能力。导入别名、动态注册、宏、编译条件、跨文件调用和框架中间件仍需结合源码确认；同名调用不等于已解析调用图，注解也不等于防护已生效。

工作包按入口和组件拆分，每包最多 24 个入口、8 个文件，不同组件轮流安排；未识别到入口的源码与配置也会进入补充工作。分析围绕输入、调用身份、租户与对象权限、受保护资源和敏感操作展开，同时查找全局中间件、共享服务、配置与反证。

主要代码：`backend/app/services/discovery/syntax.py`、`repo_index.py`、`profiles/`、`planning.py`、`prompts.py`。更多说明见 [检测与体验改进](DETECTION_AND_UX.md)。

## 3. 固定来源的专业 Skills

新增 18 个适配包：17 个用于静态审计，1 个供维护者审阅导入材料；Cloudflare 的 10 个领域模块保留在一个包中。来源为 Trail of Bits、Cloudflare 与 Sentry，固定到具体提交，保留归档哈希、许可证、适配说明和来源路径。

技能覆盖上下文梳理、代码审计、危险默认值、易误用 API、C/C++、Rust、Django 权限、凭据序列化、GitHub Actions、Agent CI、供应链、差异分析、规范一致性、变体分析和扫描反馈。

每个工作包选择一个主方法、至多一个专项和两个领域参考，按需读取正文。实际读取记录绑定文件内容、行范围与哈希；候选的 `skills_used` 由服务端根据回执生成。安装或选中技能不计为使用，读取技能也不计为源码覆盖。

主要文件：`skill_library/autocve-*/`、`skill_library/.discovery/manifest.json`、`skills_sources_manifest.json`、`skill_sources/`、`scripts/manage_audit_skills.py`。运行时仅使用适配后的资料，不执行上游归档内的脚本。完整列表和许可见 [Skills 接入说明](SKILLS_INTEGRATION.md)。

## 4. 独立 Pi 动态验证

新增与主审计流程分离的 Pi 验证服务。对漏洞管理中已有记录，后端驱动容器内 Pi Agent 获取源码、安装依赖、构建和运行目标，实际执行 PoC 或请求，再取回结构化证据。目标运行在专用 DinD daemon 中，Pi 与 daemon 共享工作卷。

- 保存命令、退出码、stdout/stderr、HTTP 请求响应、环境信息、证据产物哈希、复现步骤和限制。
- 校验 `confirmed`、`refuted`、`inconclusive`、`unverifiable` 的必要证据字段。
- 提供独立历史、报告导出和前端入口。
- 暂停/继续通过冻结/解冻验证容器实现；暂停时长单独记录。
- 后端重启时尝试回收已完成证据，其他中断如实标记，按运行标签清理环境。

Pi 不挂载宿主 Docker socket；专用 daemon 使用 privileged DinD，隔开 Docker 对象管理范围，但不提供虚拟机级隔离。暂停会影响共享该 Pi 容器的任务，默认并发保持 1；长期暂停时正在进行的外部请求可能失效。

主要代码：`backend/app/services/verification_agent/`、`backend/app/api/v1/endpoints/vulnerability_verifications.py`、`frontend/src/components/vulnerabilities/VerificationPanel.tsx`、`docker/verifier/`、`docker/verifier-dind/`、`docker-compose.verify*.yml`。配置、证据语义和操作见 [动态验证说明](DYNAMIC_VERIFICATION.md)。

## 5. 覆盖与使用体验

源码覆盖只统计可信 Read 工具实际返回的源文件范围；流程完成、扫描完成、没有发现漏洞都不能推导出源码已完整分析。旧任务缺少读取记录时显示“未记录”，不自动给出安全满分。

前端统一浅色平面样式，简化首页、侧栏、表单和表格；创建任务加入分析预设与清晰的模式说明，支持本地目录，切换项目时清理过期选择。候选支持筛选，证据以真实文件和行号展示，历史结论可展开查看。漏洞列表把报告与动态验证作为主要操作，其他操作与高级筛选按需展开。

同时修正部分任务状态轮询、创建对话框和 TypeScript 类型问题，`npm run type-check` 改为真正检查 `tsconfig.check.json` 范围。

主要代码：`backend/app/services/agent/read_coverage.py`、`backend/app/services/discovery/coverage.py`、`frontend/src/pages/AgentAudit/`、`frontend/src/components/agent/`、`frontend/src/components/vulnerabilities/`、`frontend/src/assets/styles/globals.css`。

## 6. Linux / macOS 安装与运行

新增平台预检、Compose 包装、本机启动/停止脚本；遵循 Docker context 和显式环境配置，区分宿主 CLI 地址与容器挂载 socket。共享配置不再依赖 macOS 系统代理，也不固定 DNS、代理端口或镜像站。

后端使用 Python 3.12 与锁定的 uv 依赖，补齐流式 JSON、队列、数据库驱动、多语言解析与中文 PDF 字体。前端镜像锁定 Node/pnpm，API 和 worker 共享数据卷与项目路径；默认数据库、Redis、API 和管理端口只在宿主回环地址发布。新增 macOS/Linux 脚本检查与 Linux 镜像检查的 GitHub Actions 工作流。

本次数据库迁移包括 `20261016_01`（源码发现）、`20261017_01`（独立验证）和 `20261017_02`（暂停字段）。容器启动自动迁移；本机开发通过启动脚本迁移。升级已有环境前备份数据。

安装与操作以 [README](../README.md)、[平台部署](LINUX_DEPLOYMENT.md) 和 [本地开发](LOCAL_DEVELOPMENT.md) 为准。上游 `docker-compose.prod*.yml` 仍保留原发布镜像定义，不能用于获取本 fork 新功能。

## 验证范围与当前边界

开发期间已完成源码发现、扫描、研判、技能追溯、独立验证及相关工作流的定向回归，前端类型检查与生产构建通过。平台验证覆盖 macOS 与 Linux ARM64 容器脚本、实际镜像构建、全新 PostgreSQL 迁移、API 健康检查、worker 导入、多语言解析、中文 PDF 和 DinD 启动。具体记录与命令见各功能文档。

2026-10-17 提交前检查：

| 检查 | 结果 |
| --- | --- |
| 后端 discovery / scan / triage / verification / 沙箱路径定向回归 | 130 passed，1 skipped（真实 Docker 扫描需显式开启） |
| 平台脚本回归 | 15 passed |
| 前端类型检查、生产构建 | 通过 |
| 首页、CVE 路由与登录错误提示回归 | 7 passed |
| Skills 清单校验 | 18 个适配包、35 份文本资源、3 份固定归档通过 |
| Compose、Shell 语法、文档相对链接 | 通过 |

Linux x86_64 镜像检查已配置到 CI；本次本地验证不等于已在所有发行版、物理 x86_64 或 rootless 环境中实测。没有建立漏洞检测评测体系，也不据回归测试宣称检出率或误报率改善。

本次没有实现：报告与动态验证状态自动同步、CVSS 评分规则调整、全程序语义调用图、新的语言专项扫描器、旧任务自动补齐历史覆盖、源码候选自动转为已验证漏洞，以及一键 CVE 批量自动触发独立验证。

提交只包含代码、依赖锁、公开配置示例、文档、截图与有来源记录的技能材料。本地 `.env`、运行数据、日志和技能运行索引不纳入版本管理；`skill_library/agents/*/bindings.json` 继续作为绑定配置，带本机路径的聚合镜像在启动时重建。

根目录两份 2026-10-16 的方案文档保留为设计背景；它们描述的是当时的规划，当前行为以代码和以上使用说明为准。
