# 综合源码审计 v2

本功能实现根目录设计方案的第一阶段主链路。当前新建审计窗口默认开启“使用源码发现与覆盖账本”；API 调用仍需显式传入 `discovery_v2.enabled=true`。旧任务、旧报告和旧 Finding/Triage 路径保持兼容。新模式复用现有 LLM 配置与 Finding runtime，不调用 Verification，也不生成利用执行或 CVE 申报材料。

已接入固定版本的专业静态 Skills、按场景读取与候选 `skills_used` 追溯，详见 [Skills 接入说明](SKILLS_INTEGRATION.md)。

## 本地使用

在项目根目录运行：

```bash
./scripts/compose.sh build static-scanner
./start.sh
```

`start.sh` 会安装锁定依赖并运行数据库迁移，包括 `20261016_01`。先按 [本地开发说明](LOCAL_DEVELOPMENT.md) 准备环境；Compose 部署按 [平台说明](LINUX_DEPLOYMENT.md) 启动。静态镜像 `autocve-static-scanner:latest` 使用 Semgrep 1.161.0，旧模式仍使用单独的 `sandbox` 镜像。

打开“审计任务 → 新建审计”，保持“使用源码发现与覆盖账本”开启，选择项目并填写版本标记。任务详情中的“候选与覆盖”在运行期间即可打开，包含：

- 静态支持的候选：保留严重性估计与依据，不标记为运行时 confirmed。
- 未决线索：展示未知条件，不要求 PoC、HTTP 请求或 CVE justification。
- 已排除项：保留反证、原因和版本历史。
- 原始工具告警：全量游标分页，可读取原始规则信息和数据流。查看页面不会改变研判进度。

顶部显示独立轮状态、扫描状态、原始/已索引/分组/已研判/待补查/待处理数量。覆盖区展示实际读取证据、工作包状态、延期原因、适配能力和导入异常。`partial` 使用独立状态，不能当作全部完成。可下载原始扫描 JSON，或导出包含候选全部版本、证据、任务和 observations 的 JSONL 账本。

“继续待处理工作”在原快照、原候选 ID 和已提交回执上恢复，并获得一次新的任务预算。第一轮冻结记录不改写；独立轮未完成的范围以续接工作包补查。模型崩溃后的租约可回收，旧 attempt 无权覆盖新 attempt。已发布索引不允许换成不同扫描文件；换源码或重新扫描应新建任务。

## 执行顺序与边界

1. 复制审计范围到独立源码快照，记录 commit（如有）、内容哈希、文件清单、范围和排除项。非 Git 项目使用内容清单哈希。跳过符号链接，并记录能力缺口。
2. 固定 Semgrep 规则计划，下载规则原文并保存 SHA-256，随后以只读规则挂载运行扫描。扫描容器禁止网络，原始 JSON 从容器流式导出到文件。
3. Agent 独立工作包与扫描并行。独立 worker 获得源码清单内的 Read/Grep/Glob/符号导航、账本工具，以及只读的固定 Skills 参考，不装载 shell、Write、扫描器、旧会话记忆、旧报告技能或全局 FinalizeFinding。
4. 双方到达完成、部分完成、失败或跳过边界后，冻结候选版本与未完成项。一个分支失败不会丢弃另一分支结果。
5. 反馈工作包恢复原候选、证据、覆盖和检查点；关联扫描线索，逐项研判，并申请有明确范围与新证据的补查。
6. 调度器从账本生成汇总。没有候选是正常结果，未处理项与无告警成功扫描分开记录。

源码目录在 POSIX 下设为只读；扫描结果位于快照之外，产物目录权限为 0700。扫描器使用独立 Docker 进程、只读源文件/规则挂载与非 root 用户。模型 worker 使用应用进程内的受限工具能力，不是每个 worker 一个独立 OS 用户；其文件、证据和扫描接口均做范围校验，不能依靠提示词自行越权。源码、规则消息和注释均作为不可信数据。

## 配置与 API

创建接口仍为 `POST /api/v1/agent-tasks/`。`discovery_v2` 从 API 写入 `AgentTask.agent_config` 并传到 Orchestrator，优先于旧 `finding_runtime_stack` 分流。

```json
{
  "project_id": "项目 ID",
  "version_label": "v1.0",
  "max_iterations": 50,
  "token_budget": 100000,
  "timeout_seconds": 1800,
  "discovery_v2": {
    "enabled": true,
    "worker_concurrency": 3,
    "default_batch_size": 5,
    "max_feedback_rounds": 2,
    "independent_share": 0.40,
    "feedback_share": 0.45,
    "expansion_share": 0.15,
    "write_batch_size": 1000,
    "project_profiles": ["auto"]
  }
}
```

配置采用以上扁平结构；方案中的 YAML 是设计示意，不能直接当成 API 请求。worker 上限为 3，反馈与扩展总轮数上限为 2。默认 5 条是模型批次大小、1000 是数据库写入批次，均不限制保存总量。传入旧 `max_index_findings` 会记录弃用警告并忽略。磁盘/快照限额和扫描超时可通过 `DiscoveryConfig` 调整；缺省原始产物 512 MiB、源码快照 1 GiB。

任务总轮数按 40% / 45% / 15% 分配，前阶段余额可向后释放。模型调用前按上下文、工具 schema 与输出上限预留 token，返回后以提供方 usage 结算；预估不能代替账单精确计量。预算或时间用尽时保留已提交候选、读取范围和待处理项。支持继承工作流的 finding/scan 启用状态；新模式的反馈步骤由确定性调度器控制，旧 verification 开关不触发动态验证。

环境变量：

```dotenv
DISCOVERY_STORAGE_PATH=./uploads/discovery_v2
DISCOVERY_SCANNER_IMAGE=autocve-static-scanner:latest
```

本机开发时，`DISCOVERY_STORAGE_PATH` 必须位于 Docker 可访问的目录。macOS 外置硬盘未共享给 Docker 时，可在 `backend/.env` 将它设为用户主目录下已共享目录的绝对路径；不要照搬其他机器路径。Compose 部署会统一设置为共享卷 `/app/uploads/discovery_v2`。

新 API 均校验任务创建者/项目所有者权限：

| 方法与相对路径 `/api/v1/discovery` | 用途 |
| --- | --- |
| `GET /tasks/{task_id}` | 阶段、画像、覆盖、扫描 manifest、导入异常 |
| `GET /tasks/{task_id}/candidates?status=needs_context` | 候选列表与状态筛选 |
| `GET /tasks/{task_id}/candidates/{candidate_id}/history` | 不可变候选版本 |
| `GET /tasks/{task_id}/evidence/{evidence_id}` | 绑定快照/内容哈希的真实证据 |
| `GET /tasks/{task_id}/observations?cursor=...&page_size=100` | 稳定优先级/ID 游标；支持 severity/file_path 筛选 |
| `GET /tasks/{task_id}/observations/{observation_id}` | 完整原始记录与 trace |
| `GET /tasks/{task_id}/artifact` | 原始扫描文件 |
| `GET /tasks/{task_id}/export` | 流式 JSONL 账本 |
| `POST /tasks/{task_id}/resume` | 恢复待处理工作 |

页面游标不用于任务领取。工作包以事务/CAS、租约、attempt ID 与逐项回执推进。漏答的 observation 保持 pending，不能因模型返回了其它决策而自动完成。follow-up 可以生成新候选，也可以追加原候选版本；原 observation 的决策历史保留。

## 数据与适配能力

七张新增关系表分别存运行/冻结快照、任务/覆盖、候选当前版本、候选历史、证据、全量 observations 和导入异常。旧 `AgentFinding` 记录不迁移、不改写。

扫描使用 ijson 流式读取，每条可解析 occurrence 都保留独立 ID。signal fingerprint 只做关联/调度，不删除重复 occurrence。未知级别保留 unknown，原始等级与模型严重性分离；`.github` 等真实路径组成保留，越界路径记入异常清单。文件不可解析时 raw_count 为 null。原始产物先保存，索引写入失败或取消后可以用相同产物幂等重建，不能把不同扫描输出覆盖到已经发布的索引上。

已实现的入口画像为 Web/API、库/SDK、CLI、后台任务/队列服务，一个仓库可同时拥有多个标签。Python 保留原生 AST；JS/TS、Java、Go、C#、PHP、Ruby、Rust、Kotlin、Swift、C/C++ 使用 tree-sitter 补充定义、导入和调用表达式导航，框架注册另以显式规则识别。调用者名称匹配会标注未解析，不能当作精确跨语言调用图。宏、动态注册、编译条件、解析失败与未支持语言如实记录能力缺口。具体入口与信任边界见 [检测改进说明](DETECTION_AND_UX.md)。

`FindSymbol` / `FindReferences` / `GetCodeContext` / `GetEntryPointContext` 返回真实代码位置和解析依据。guard、配置与测试提供导航位置，实际安全条件由源码研判确认，不根据名字自动认定存在防护。

## 验证与已知限制

自动回归覆盖方案 T01–T18 对应的主链路，包括 201 条告警、不同模块轮转、独立性、版本/反证、缺失回执、租约重试、预算延期、非 Web 入口、源文件注入、损坏产物和分页。另有 API 权限/配置/导出测试，以及复用真实 runtime 的固定模型工具调用测试。这些测试不代表真实漏洞发现率。

```bash
cd backend
uv run pytest -q -o addopts='' tests/discovery tests/scan_runtime tests/triage_runtime
# 真实 Semgrep 容器与公共规则下载，需要已构建 static-scanner：
AUTOCVE_RUN_DOCKER_TESTS=1 uv run pytest -q -s -o addopts='' tests/discovery/test_discovery.py::test_real_semgrep_docker_artifact_to_full_index
```

Colima 上运行真实容器测试时，增加 `--basetemp="$HOME/.cache/autocve-discovery-docker-tests"`，确保测试快照也位于 Docker 可访问的目录（pytest 会清理该专用测试目录）。

开发验证覆盖 discovery、scan、triage、相关工作流和独立验证路径。真实 Semgrep 1.161.0 容器曾扫描 4 个测试源文件，产出 1 条告警，原始与索引数量均为 1；PostgreSQL 迁移与固定模型 runtime 冒烟也已通过。固定模型用于验证链路，不用于估计漏洞发现率。

2026-10-17 已修复此前记录的 TypeScript 基线错误，`npm run type-check` 现在使用 `tsconfig.check.json` 检查源码；类型检查与生产构建均通过。平台构建、解析器与 PDF 验证记录见 [部署说明](LINUX_DEPLOYMENT.md)。

第一版实际接入的扫描器只有 Semgrep。规则下载失败、扫描器缺失、扫描零目标、解析/存储不完整均单独记录，不显示成“无告警成功”。旧扫描的原始产物不齐全时，不推断缺失记录已恢复；旧报告仍在旧入口查看。尚未实现新的语言专项扫描器、精确全程序调用图或历史旧任务自动迁移。
