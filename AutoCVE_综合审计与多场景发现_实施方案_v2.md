# AutoCVE 综合审计与多场景发现：第一阶段实施方案

> 设计背景文档（2026-10-16），保留当时的规划与来源核对。部分内容已落地，当前功能和安装方法以 [README](README.md)、[改动清单](docs/FORK_CHANGES.md) 及对应功能文档为准。

**版本：v2 · 日期：2026-10-16**
**定位：以 AutoCVE 为骨架，建设实用的源码安全审计工具。**
**范围：独立发现、工具扫描、扫描结果反馈、源码研判、定向扩展、候选与覆盖管理。**

本文不设计动态漏洞验证、利用执行、CVE 申报或研究型评测。这里的“判断是否存在”指依据源码、调用关系、配置和安全规则作出有依据的判断；无法确定的条件如实保留，不包装成运行时确认。

源码分析基线为 AutoCVE 提交 `b26025f27199ba2d93145e4a08fc9015e8d846e4`。实现前应对照本地提交与实际启用的 runtime 路径。除“现有实现”部分外，本文的接口、配置和模块均为**建议新增或调整的设计，不是目前已经实现的功能**。本文不附修改后的源码，也不宣称已测得准确率提升。

---

## 1. 先确定三个产品决策

| 关注点 | 本方案的决定 | 不采用的做法 |
|---|---|---|
| 综合审计怎样协作 | Agent 和扫描器先独立工作、分别保存结果；完成第一轮后，再把工具结果与 Agent 的原始记录一起交给模型，开展源码研判与定向扩展 | 不只把两份报告相加；也不在独立轮尚未结束时，持续把扫描器结果灌入模型 |
| 如何解决前 200 条截断 | 原始结果完整保存、全部可解析结果入索引；模型通过分页和任务队列按预算分析 | 不把 200 换成另一个更大的固定截断值；不把“未分析”当作“无问题” |
| 是否只支持 Web | 使用通用源码审计内核，按项目类型加载入口模型、上下文工具、检查项和扫描器适配器 | 不要求所有问题都具有 HTTP 入口、Web PoC 或相同的 source→sink 模板 |

**推荐的产品形态：一个确定性调度器、少量专项 worker、三个逻辑持久化账本。**

优先保持现有模型与部署方式不变。先打通信息流、保存机制和任务边界，再决定是否需要调整模型。

## 2. 现有实现与本次改造的关系

### 2.1 已核对的关键实现

| 位置 | 基线实现 | 对本方案的影响 |
|---|---|---|
| `agent/agents/orchestrator.py` | 主流程为 Recon → Finding → Scan → Triage → 合并；Finding 收到的前序信息只有 Recon；Finding 失败会提前返回 | 必须修改编排，而不只是调整提示词。[S1] |
| `scan_runtime/pipeline.py`、`normalizers/semgrep.py` | 默认 `max_index_findings=200`，按原始顺序截断，再对保留下来的索引排序 | 需要分离结果保存、索引和模型分析预算。[S2]、[S3] |
| `agent/agents/recon.py` | 入口描述包含 HTTP 路由、调度任务、队列消费者等；技术栈识别不只面向单一语言 | 内核并非只能处理 Web，但入口画像需要系统化扩展。[S4] |
| `agent/agents/finding.py`、`final_finding_contract.py` | 提示词与结果契约偏向高危/CVE/完整 PoC，PoC 模板明显偏 HTTP | 非 Web 支持不能只增加几个关键词；需要调整任务与候选契约。[S5]、[S6] |
| `finding_runtime/`、`runtime_core/` | 已有会话、技能、工具、上下文管理等基础设施；`FinalizeFinding` 为终止工具 | 复用运行时，增加非终止保存与任务级结束机制，不另建第三套 Agent 框架。[S7]、[S8]、[S9] |

以上路径均相对于 `backend/app/services/`。

### 2.2 对“是不是只能审 Web”的直接回答

**不是只能审 Web，但也不能把“能够读非 Web 源码”理解为“已经成熟支持所有非 Web 场景”。**

AutoCVE 的文件读取、搜索、模型调用和任务运行能力可以复用；目前更明显的限制在入口识别、检查目标、证据表达和最终输出要求。扩展到库、CLI、解析器或后台服务，主要应改这些层，而不是另写一套产品。[S4]、[S5]、[S6]、[S8]

第一版建议优先覆盖 **Web/API、库/SDK、CLI、后台任务与队列服务**；保留解析器、原生代码和配置审计的扩展接口。支持程度应在界面明确显示，不把缺少语言或框架适配的项目标成“完整支持”。

---

## 3. 总体流程：先独立发现，再反馈，再定向扩展

```text
固定源码快照 + 文件/符号索引 + 项目画像
                      │
              ┌───────┴────────┐
              │                │
      A1. Agent 独立审计   A2. 工具独立扫描
      按入口/安全问题分工   按已确定的扫描计划执行
      增量记录候选和覆盖   保存原始产物和全量索引
              │                │
              └───────┬────────┘
                      │
       汇合点：冻结双方第一轮结果及未完成项
                      │
        B. 扫描结果反馈 + 既有记录恢复
        关联已有候选 / 研判工具独有线索
        补齐调用上下文 / 处理矛盾与反证
                      │
        C. 定向扩展与缺口补查（有界）
        相似调用点 / 相邻入口 / 共享组件
        尚未完成的独立攻击面
                      │
        D. 汇总第一阶段结果和剩余工作
        静态支持的候选 / 已排除项 / 未决项
        原始工具告警 / 实际覆盖 / 执行故障
```

这是**同一个第一阶段中的几轮源码分析**，不是增加后续动态验证流程。

### 3.1 准备阶段：建立共同的事实底座

固定 `repo_snapshot_id`、commit、源码内容哈希、审计范围和规则版本。非 Git 导入使用内容清单哈希；同一轮禁止模型改写被审计源码。

建立轻量索引：文件、函数/类、导入关系、入口、公共权限检查、配置定义。Recon 在这些信息上补充项目角色、信任边界和审计任务。

Agent 与扫描器可以共享同一份源码快照、范围和技术栈画像。扫描计划在独立轮开始前确定；**扫描器告警、漏洞结论和中间报告不提前共享**。

### 3.2 A1：Agent 独立审计

调度器根据项目画像生成有明确边界的任务，例如“导出操作的对象权限”或“公开解析 API 的长度约束”。worker 使用源码导航工具和适用 skills，增量保存：

- 已提出的候选及其版本、证据、未知条件；
- 已排除的假设及排除理由；
- 已检查的入口与检查项，以及尚未完成的范围。

独立审计应有明确预算，不要求先审完所有文件才进入反馈轮，也不以找到几个漏洞为结束条件。预算用尽时保存检查点，未完成任务进入 `deferred`。

第一轮结果不能只是一段聊天摘要。应有稳定的候选 ID、任务 ID、证据引用和版本，供反馈轮恢复。

### 3.3 A2：工具独立扫描

扫描器按技术栈适配器运行，与 Agent 分支并行。首先复用现有 Semgrep 路径，后续再增加语言专项、依赖和配置检查工具。

每次扫描记录工具/规则版本、参数、目标文件、排除项、退出状态、原始产物、索引进度和诊断。**工具失败、不支持目标语言、规则覆盖不足与成功扫描但无告警，是不同状态。**

基线的确定性 `ScanPipeline` 只执行 Semgrep；Recon 推荐其他工具并不等于这条路径已经调用了它们。新增工具必须真正接入执行、解析、落库和状态展示。[S2]、[S4]

### 3.4 独立性的工程实现

不能只在提示词里写“不要看扫描结果”。建议做到：

1. Agent 独立 session 的检索与记忆查询过滤扫描来源数据；原始扫描产物放在独立存储区。
2. Agent 的 `Read/Grep/Glob` 只读源码快照和允许的项目资料，不读另一个分支的产物目录。
3. 独立轮不暴露可自行运行相同扫描器的工具；确需 shell 的内部静态解析命令由受控适配器执行。
4. 使用进程/文件权限隔离产物访问，而不是仅依赖模型遵守目录约定。

这是一项流程与结果来源隔离措施，不是宣称两个分析过程在统计上完全独立。旧审计记忆如包含该快照的扫描结论，也不能偷偷注入独立轮。

### 3.5 汇合点与失败处理

当两个分支各自达到 `completed / partial / failed / skipped` 后，形成不可变的 `initial_snapshot`，记录双方产物版本以及未完成范围。全局任务取消另行处理，不伪装为正常完成。

一个分支失败不取消另一个分支已经取得的结果。若扫描失败，仍可输出独立审计结果，但清楚标记缺少扫描反馈；若 Agent 独立轮失败，扫描结果仍可进入反馈分析，但不能声称完成了独立审计。

为避免单个分支无限阻塞，使用现有任务截止时间和分支预算。到达限制时保存检查点并以部分结果汇合。

---

## 4. 反馈阶段怎么做，才能同时减少误报并发现更多问题

### 4.1 反馈单位：相关线索包，而不是完整扫描 JSON

先用确定性规则按模块、函数、代码位置和问题类型关联扫描项与已有候选。关联有歧义时保留多个关系，不强制合并。

每个反馈任务得到一个小型上下文包：

```text
当前审计问题与源码快照
本任务相关的原始候选 ID、版本和关键证据
相关扫描 observation IDs、规则信息和原始产物位置
已检查的防护、已排除假设、尚未解决条件
可按需查询的调用者、入口、配置和测试位置
本轮任务预算与完成条件
```

默认先给少量相关告警预览；需要时通过 ID 读取原始规则信息、完整命中和数据流轨迹。不能只给模型一段丢掉条件、路径和位置的工具摘要。

### 4.2 原 Agent 的记录怎样继承

优先把任务交回同一专业方向的 worker，恢复其任务记录。历史不长时继续既有 session；过长、故障或已结束时，用结构化记录创建续接 session。

**“继续分析”不要求强行复活已经调用终止工具的会话。**关键是保留任务身份、候选版本、原始证据和未决问题。

第一轮不要调用现有全局 `FinalizeFinding` 来保存中间结果。新增 `RecordCandidate` 和 `CompleteAuditTask`；后者只结束一个工作包，不结束整轮综合审计。[S7]

### 4.3 四类反馈任务

| 情况 | 模型应完成的工作 | 应保存的结果 |
|---|---|---|
| Agent 与工具命中相关位置 | 对照原始源码，检查是否为同一问题，补齐或推翻原候选的条件 | 新候选版本、支持/反对证据、扫描来源关联 |
| 只有工具命中 | 从命中位置追踪调用者、可控输入、公共防护与配置，判断是否形成安全问题 | 新候选，或带证据的排除理由，或未决项 |
| 只有 Agent 提出候选 | 继续保留并分析，不因扫描器无命中而删除；必要时补充上下文 | 独立来源候选及分析进展 |
| 双方信息矛盾或暴露新边界 | 把矛盾转成具体源码问题，并申请定向补查 | 有范围、证据目标明确的 follow-up 任务 |

**工具命中不是证明；Agent 和工具同时报告也不是两票确认。**真实性与严重性分开处理，不能为了符合高危输出限制而夸大影响。

### 4.4 强制完成两项工作，而不是只做真假分类

**工作一：源码研判。**核对入口、调用条件、权限、净化或边界检查、默认配置，以及实际违反的安全规则。每个结论附可核对的证据。

**工作二：定向扩展。**对有价值的线索，检查相关调用者、共享 helper、相似入口、不同配置模式和未覆盖的相邻操作。即使一个告警被排除，其揭示的公共敏感操作仍可成为有依据的导航线索。

模型可以申请补查，但必须给出：`why_new`、具体范围、已有证据、想解决的问题。只有“再看看有没有更多漏洞”不构成可调度任务。

### 4.5 一个非 Web 的假设例子

项目包含 CLI、共享文件处理库和后台队列 worker。扫描器对公共写文件 helper 提示路径风险。

Agent 独立轮已经记录：CLI 的输出路径由本地调用者主动指定，尚未发现跨权限边界；不能仅凭“可以指定路径”认定漏洞。

收到扫描结果后，模型读取同一 helper 的调用者，发现后台 worker 也使用它，且路径来源不同。此时应分别分析：CLI 路径是否为设计功能；队列消息的来源与权限是否可信；后台调用是否有输出范围约束。信息不足时保存未知条件，并创建后台调用链补查任务。

最终可以是“CLI 告警被排除，但新增后台调用候选”，也可以两处都被排除。**发现更多来自新增上下文，不是要求模型增加报告数量。**这个例子只说明设计行为，不指向任何实际项目漏洞。

### 4.6 约束扩展，避免无限循环

首版建议反馈与扩展最多进行两轮；同一问题每轮只有获得新证据、发现新入口或明确缺口时才继续。

调度去重键包含 `repo_snapshot + scope + analysis_question + evidence_version`。重复任务合并；因预算未做完的任务保留 `deferred`，不是 `ruled_out`。

可先将模型总预算按独立审计 40%、反馈 45%、扩展 15% 预留；完成阶段的余额可以释放，但独立轮不能提前透支反馈预算。比例和轮数都是建议初始值，不是实测最优值。没有扩展任务时不强行消耗预算。

---

## 5. 前 200 条截断问题：全量索引、分页读取、预算调度

### 5.1 根因与修复目标

基线按扫描原始顺序取前 200 条，然后排序。因此第 201 条以后即使优先级更高，也不会进入这个待分析索引。原始产物可能仍在，问题在后续消费路径看不到它们。[S2]、[S3]

修复后的约束为：

> 凡扫描器已经产出且可以解析的结果，都可以通过索引定位；任何模型分析上限只控制“本轮处理多少”，不控制“系统保存多少”。

这不等于物理存储无限。触及磁盘配额或扫描器自身输出上限时，必须明确标记不完整，并保存已有产物、停止位置和原因。

### 5.2 三层处理，不把所有告警都当成漏洞候选

| 层 | 保存内容 | 数量策略 |
|---|---|---|
| 原始产物 | 扫描器完整 JSON/SARIF 等输出、日志、版本和命令元数据 | 不按模型预算裁剪；写入失败需显式报告 |
| `ScanObservation` 索引 | 每条可解析原始结果的位置、规则、原始严重性、摘要、原文引用和处理状态 | 全量保存；批量或流式入库 |
| 分析任务与 `Candidate` | 模型真正处理的工作包，以及有待分析或有源码支持的问题命题 | 按预算创建/消费任务；剩余 observation 保持待处理 |

**几千条工具告警不应直接变成几千条“漏洞”。**原始告警数量、去重分组数量、已分析数量和候选数量分别展示。

### 5.3 修改扫描导入路径

```text
扫描器输出 → 原始产物落盘并计算哈希
          → 逐条解析/批量标准化
          → 写入全部 ScanObservation
          → 生成 manifest 与统计
          → 发布可消费的结果快照
          → 调度器领取分析工作包
```

移除发现 v2 路径中的固定数量 `break`。同时检查 executor、`_combine_index()`、结果存储和 Triage：不能只改 normalizer，却在下游再次 `[:200]`。

小结果允许一次解析；大结果从文件流式解析并分批写库，避免“取消 200 上限”后把整个大 JSON 多次复制到内存。原始输出先保存，索引失败后可以从产物恢复，而不必重新扫描。

解析失败的记录放入异常清单，记录原始位置和原因；不能无声跳过。整份产物不可解析时保留原始文件，数量未知就显示未知，不填写零。

### 5.4 ID、去重与来源保留

推荐区分两个 ID：

- `observation_id`：绑定扫描运行、工具、原始产物哈希与原始记录位置，用于幂等导入和追溯。
- `signal_fingerprint`：按规则、标准化位置、相关代码/调用路径等建立关联，用于减少重复分析，不替代原始记录 ID。

即使多条结果被归到同一组，每个原始 occurrence 仍可找到。不同扫描器、不同入口、不同权限条件不能仅因落在同一个 sink 就删成一条。

路径标准化保留 `.github` 等真实路径组成；不使用会把有效前导字符一起去掉的通用字符剥离方式，也不允许通过路径归一化越出源码快照。

### 5.5 索引字段

```text
observation_id, scan_run_id, repo_snapshot_id
scanner_name, scanner_version, rule_id, ruleset_version
file_path, line_start, line_end, related_locations
severity_raw, severity_normalized, severity_mapping_version
message_preview, artifact_id, raw_record_locator
signal_fingerprint, source_trace_refs
review_status, linked_candidate_ids, review_evidence_refs
created_at, record_version
```

扫描器告警等级与漏洞严重性不是同一概念。保存原始等级及映射版本，模型另行给出 `severity_estimate` 和依据。未知等级保持未知，不随意赋成 high。

### 5.6 分页读取和任务领取分开

建议接口：

```text
ListScanObservations(scan_snapshot_id, filters, cursor, page_size)
GetScanObservation(observation_id, include_raw, include_trace)
ClaimFeedbackBatch(run_id, worker_id, task_scope, batch_size)
SubmitFeedbackDecisions(batch_id, attempt_id, decisions)
```

列表使用稳定结果快照和游标分页，不依靠会随着插入而漂移的 offset。若按优先级展示，应固定排序版本，并用优先级与 ID 组成稳定排序键；重新打分生成新排序版本。

**前端翻到了第几页，不代表模型已经分析了那些记录。**实际消费通过任务租约和完成回执推进，不借用 UI 分页游标。

每个反馈批次要求返回全部领取项的处理状态：关联候选、新建候选、依据明确的排除、需要补查。漏答的项保持未完成，不自动标成已处理。

### 5.7 优先级只决定顺序，不决定是否存在于索引

首版建议综合扫描器等级、入口线索、独立候选关联、模块覆盖和等待时间。工具自报置信度不是唯一排序依据。

为避免同一类重复告警占满预算，可使用“高优先级优先 + 模块/问题类型轮转 + 等待项补位”。高优先级组内部也进行适度分散，确保不同模块能获得处理机会。具体比例先保持简单可配置。

批量相似项可以共享上下文，但只有证明相关调用条件与防护一致时才复用判断；不能分析一条就自动排除其余几百条。

### 5.8 预算不足和错误怎样展示

必须分别统计：

```text
扫描器原始记录数（未知时为 null）
可解析并已索引数量
解析异常数量 / 尚未导入数量
关联分组数量
已完成研判数量 / 待补查数量 / 尚未处理数量
本轮延期数量和原因
```

建议初始设置：索引写入批次 1000 条，列表每页 100 条，模型每次默认 5 条相关告警。单条告警上下文很大时缩成 1 条；按上下文预算调整批次。**这三个数字均不是总量截断值。**

已有 API 的 `index_ref` 如果被调用方当成 JSON 数组，不能悄悄改为 manifest 对象。新增 `index_manifest_ref` 和分页接口，版本化升级消费者；兼容导出也不能静默截断。

### 5.9 并发、恢复和配额

复用现有关系数据库事务领取任务，记录 worker、租约、尝试编号和心跳。worker 崩溃后租约可回收；结果提交使用幂等键，防止“已保存结果但未确认完成”导致重复候选。

不假设任务恰好执行一次，而是按可能重试设计。候选更新采用版本检查，过期更新不能覆盖新证据。

索引或存储配额不足时设置 `ingestion_incomplete`，保存导入游标和产物，任务整体为部分完成。扫描器本身超时、跳过文件或输出受限，也需展示其覆盖缺口；全量索引并不等于工具已经扫描完整仓库。

---

## 6. 一个调度器、少量专项 worker、三个持久化账本

### 6.1 调度器负责确定性控制

调度器负责阶段切换、任务生成、范围分配、预算预留、结果关联、去重、重试、进度和最终汇总；不要把这些都交给一个“总管模型”自由决定。

worker 可以提出补查建议，但不能无限创建子 Agent，也不能自行宣布全局审计完成。

首版从 **3 个并发 worker** 起步。worker 类型是能力模板，不要求为每种能力常驻一个进程；有工作才实例化，完成后释放。

| 能力模板 | 审计问题 | 可用于哪些场景 |
|---|---|---|
| 权限与信任边界 | 谁能调用什么、控制什么、访问什么资源 | Web、后台任务、IPC、插件、服务账户 |
| 输入与敏感操作 | 输入如何传播、转换和受约束 | Web、库、CLI、文件处理、外部集成 |
| 状态与资源生命周期 | 状态转换、次数约束、对象/资源生命周期是否一致 | 业务流程、队列、协议、原生组件 |
| 配置与集成 | 默认值、配置覆盖、依赖声明和外部数据边界 | SDK、CLI、部署配置、自动化任务 |

“原生资源生命周期”需要相应语言支持，不能仅换一个角色提示就宣称有精确分析能力。

### 6.2 三个账本各管什么

三个是**逻辑职责**，不是必须只有三个数据库表，也不意味着要部署三个数据库。

| 账本 | 记录内容 | 回答的问题 |
|---|---|---|
| 任务与覆盖账本 | 阶段、工作包、入口/检查项、任务状态、租约、预算、检查点、已读范围、未完成原因 | 看过哪里？还缺什么？由谁接着做？ |
| 候选账本 | 安全问题命题、来源、版本、支持与反对依据、未知条件、关联扫描项、最终静态状态 | 发现了什么？依据是什么？结论为什么改变？ |
| 证据账本 | 原始扫描产物、全量 observation 索引、源码片段、配置/文档/测试引用及哈希 | 模型依据的原始材料是什么？还能否重新读取？ |

复用现有数据库、会话和产物存储。原始大文件存文件系统或现有对象存储，数据库保存可检索元数据、哈希和引用。

### 6.3 候选契约：面向安全问题，而非申报材料

```json
{
  "candidate_id": "cand-example",
  "repo_snapshot_id": "snapshot-example",
  "record_version": 2,
  "initial_version": 1,
  "origin": "independent_agent",
  "contributing_sources": ["independent_agent", "scanner_feedback"],
  "project_component": "queue-worker",
  "analysis_kind": "trust_boundary",
  "status": "needs_context",
  "severity_estimate": "unknown",
  "claim": "后台文件操作可能缺少预期的输出范围限制",
  "expected_policy": {
    "text": "后台任务只能写入该任务的指定输出目录",
    "basis_kind": "documentation",
    "evidence_ids": ["evidence-policy-example"]
  },
  "attacker_capabilities": ["队列消息来源与提交权限尚待核对"],
  "entrypoint_refs": ["entry-worker-example"],
  "supporting_evidence_ids": ["evidence-callsite-example"],
  "counter_evidence_ids": [],
  "scanner_observation_ids": ["obs-example"],
  "controls_considered": ["CLI 调用中的输出路径选择属于独立使用场景"],
  "unknowns": ["是否存在覆盖该后台调用的上游路径限制"],
  "followup_task_ids": ["task-example"]
}
```

这是结构示意，ID 和问题均为例子，不是真实发现。政策依据可以来自代码、文档、测试、用户指定规则或明确标记的假设；文档声称与代码事实分别保存。

允许 `critical/high/medium/low/info/unknown`；不强制 PoC、HTTP 请求、CVE justification。静态阶段默认状态为 `needs_context / statically_supported / ruled_out`，不输出含糊的 `confirmed`。

证据 ID 由工具层生成并绑定真实内容，不由模型凭空编造。模型提交引用时检查存在性和快照一致性；这只能保证引用真实存在，不能替代安全语义判断。

### 6.4 任务级工具与结束语义

新增或适配：

```text
RecordCandidate / UpdateCandidate
GetCandidate / GetEvidence
RecordCoverage
RequestFollowup
CompleteAuditTask
```

独立发现和反馈 worker 不加载全局最终报告终止工具。完成一个工作包后，只返回已保存的 candidate IDs、覆盖项和未决任务。最终输出由调度器从账本读取，不依赖 worker 自述“我已提交报告”。

Bridge、恢复提示、工具注册和结果校验要一起调整，避免 worker 被旧的 nudge 提示再次强迫调用 `FinalizeFinding`。[S7]、[S8]

### 6.5 最小源码导航能力

在现有 `Read/Grep/Glob` 上增加：

```text
FindSymbol(name, module_hint)
FindReferences(symbol_id)
GetCodeContext(symbol_id, include=[callers, callees, guards, config, tests])
GetEntryPointContext(entrypoint_id)
```

返回解析依据和实际代码位置。解析器确认的引用、启发式名称匹配、未解析动态调用明确区分。不要在第一版追求完整跨语言全程序调用图，也不要把向量数据库当成必需组件。

---

## 7. 多场景支持：通用内核 + 项目画像 + 适配器

### 7.1 一个仓库允许多个项目标签

不要把 `project_kind` 设计成只能四选一。一个仓库可能同时包含 SDK、CLI、Web 管理端和后台 worker，漏洞也可能出现在它们共享的组件。

建议项目画像：

```text
project_kinds[] / components[] / languages[] / frameworks[]
entrypoints[] / actors[] / protected_resources[]
trust_boundaries[] / shared_guards[] / configuration_defaults[]
security_contracts[] / applicable_checks[]
analysis_capabilities[] / unsupported_features[] / unknowns[]
```

入口不统一叫“路由”，而使用 `kind + locator + input_contract + caller_context`。共同内核只关心谁控制输入或操作、经过什么代码、跨越什么边界、应遵守什么规则。

### 7.2 建议支持范围

下表是适配设计，不代表现有 AutoCVE 已经对所有类别提供成熟支持。

| 场景 | 应识别的入口 | 第一阶段重点 | 容易误判的地方 |
|---|---|---|---|
| Web/API | 路由、GraphQL/RPC 方法、WebSocket 消息、管理接口 | 认证、授权、对象边界、输入传播、业务状态 | 把“已登录”当成对象授权；忽略公共中间件 |
| 库/SDK | 公开函数、导出类、回调、反序列化/API 入口 | 参数契约、默认配置、调用方边界、危险能力的安全约束 | 把调用者主动使用的通用能力当成库自身漏洞 |
| CLI/开发工具 | 命令、子命令、stdin、环境变量、项目文件、配置 | 可信与不可信文件、进程权限、输出约束、外部命令参数 | 把用户有权指定的本地路径当成越权；忽略 CI 或提权运行场景 |
| 后台服务/队列 | 消费者、定时任务、RPC/IPC、任务处理器 | 消息提交权限、任务归属、信任转换、重试和状态约束 | 把“来自内部队列”直接视为可信 |
| 文件/协议解析器 | parse/decode/load、格式分派、长度字段和状态入口 | 长度与整数约束、递归/资源边界、路径与格式状态 | 没看到外部 HTTP 调用就排除；静态疑点直接写成已发生崩溃 |
| 配置/IaC/自动化 | 配置声明、模板、工作流事件、变量和秘密引用 | 默认权限、信任级别、配置合并、敏感信息暴露 | 将开发示例或未生效配置直接当作生产问题 |
| 插件/Agent 工具系统 | 插件注册、工具描述、权限映射、任务与数据输入 | 调用授权、数据和指令的边界、权限继承、状态约束 | 把不可信仓库文本当作当前审计 Agent 的指令 |

C/C++、Rust 或原生扩展属于语言能力维度，可以叠加在库、CLI、解析器等场景上。对象生命周期、指针别名、宏和条件编译等问题需要相应分析支持；只有通用文本检索时，应显示“基础源码分析”，不能保证完整覆盖。

纯二进制、固件镜像或只有运行地址的目标不作为本版完整支持对象。它们需要另外的反汇编、固件解析或运行时工作流，不能仅增加 profile 就宣称支持。

### 7.3 不同问题使用不同证据结构

| 分析类型 | 必须表达的核心内容 |
|---|---|
| 数据流问题 | 输入、传播、转换、检查、敏感操作 |
| 权限/信任边界 | 主体、对象、操作、权限规则、权限检查位置 |
| 状态/业务问题 | 前置状态、操作、状态变化、应保持的约束 |
| 解析/资源问题 | 输入尺寸或结构、边界检查、计算关系、资源/生命周期条件 |
| 配置问题 | 配置项、默认值、覆盖路径、生效位置与部署假设 |

这些结构共享候选与证据账本，不必为每种类型建立一套结果系统。

### 7.4 适配器要做实，而不只是换提示词

每个 `ProjectProfileAdapter` 至少提供入口发现、上下文补全、检查项选择和能力说明。每个 `ScannerAdapter` 提供适用性判断、执行、标准化、诊断和覆盖信息。

先实现实际常用语言的公开 API、命令注册、任务入口和框架路由。尚未支持的语言保留文本检索与人工指定入口能力，并记录能力缺口，不自动跳过后宣称审计完成。

解析失败、没有 compilation database、宏配置未知或动态注册未解析，都应进入项目 `unknowns`。无需为读取源码自动启动目标应用。

---

## 8. 配置示意与界面行为

以下为拟新增 v2 配置的设计示例，**不能直接粘贴到当前 AutoCVE 当成已支持参数**。

```yaml
discovery_v2:
  enabled: true
  workflow: independent_then_feedback
  project_profiles: [auto]
  worker_concurrency: 3
  allow_recursive_worker_spawn: false
  source_access: read_only

  independent_phase:
    scanner_results_visible_to_agents: false
    freeze_initial_snapshot: true

  feedback:
    inherit_candidate_records: true
    default_batch_size: 5
    allow_targeted_expansion: true
    max_feedback_rounds: 2

  budget:
    source: existing_task_budget
    independent_share: 0.40
    feedback_share: 0.45
    expansion_share: 0.15
    on_exhausted: checkpoint_and_defer

  scan_ingest:
    index_limit: null
    write_batch_size: 1000
    list_page_size: 100
    preserve_raw_artifacts: true
    on_storage_limit: mark_incomplete_and_checkpoint

  reporting:
    default_view: statically_supported_candidates
    keep_unresolved: true
    keep_ruled_out: true
    require_poc: false
    require_cve_justification: false
```

`index_limit: null` 表示不按告警条数截断，不代表取消磁盘、任务时间或资源配额。

界面建议保留四种视图：静态支持的候选、未决线索、带理由的已排除项、原始工具告警。每条候选显示来源标签：独立发现、工具反馈、定向扩展，可同时具备多个标签。

顶部显示双方第一轮状态、反馈进度、未处理告警和覆盖缺口；`partial` 不能展示成绿色“全部完成”。当所有适用任务均已处理但未发现候选，可以正常输出空结果，而不是补齐最低漏洞数量。

---

## 9. 分文件实施顺序

### 9.1 先确认实际路径

检查本地 commit、任务保存的 `finding_runtime_stack`、API 默认值和模型任务配置。仓库包含 legacy 与 runtime；不能只修改旧 `FindingController`，却让产品继续走未修改的新路径。[S5]、[S9]

建议通过显式 `discovery_v2` 功能开关上线新流程，保留旧模式作为兼容入口。新配置必须在 API、任务持久化和运行时之间透传，不能只停留在前端。

### 9.2 改动清单

下列路径相对于 `backend/app/services/`；`discovery/` 下为建议新增模块。

| 批次 | 文件/模块 | 改动 | 最小完成标准 |
|---|---|---|---|
| A | `scan_runtime/normalizers/semgrep.py`、`executors/semgrep.py`、`pipeline.py`、`store.py` | 全量索引、原始引用、导入诊断、manifest 与分页 | 第 201 条及之后仍可被查询和调度 |
| A | 新增 `discovery/models.py`、`candidate_store.py`、`task_store.py`、`evidence_store.py` | 三账本数据契约、版本、事务与幂等写入 | 保存候选不依赖完整 PoC，不因重试重复增殖 |
| B | `agent/agents/orchestrator.py` | 独立并行分支、汇合快照、反馈轮、部分失败处理 | 工具结果在独立轮结束后才发布；分支失败不丢其他结果 |
| B | `finding_runtime/bridge.py`、`adapters/finding.py`、`runtime_core/runtime_tool_registry.py` | 独立 worker session、记录恢复、增量工具、任务级完成 | 结束工作包不结束全局综合审计 |
| B | `triage_runtime/` 及批次工具 | 从全量索引领取相关工作包；逐项保存研判与补查 | 不再只返回过滤后的少量高危报告；未处理项可恢复 |
| B | 新增 `discovery/feedback_planner.py`、`scheduler.py` | 候选关联、原记录恢复、定向扩展、任务去重和预算 | 既能排除线索，也能产生有依据的新任务 |
| C | `agent/agents/recon.py`、相关 schemas；新增 `discovery/profiles/` | 多标签项目画像、入口模型、安全规则与能力矩阵 | 库、CLI、队列任务不依赖 HTTP 字段 |
| C | 新增 `discovery/repo_index.py`、`context_builder.py` | 符号、引用、配置与检查上下文 | 可追踪跨文件依赖，并显式显示未解析关系 |
| 配套 | Finding/Triage 提示词、恢复提示、候选 API、数据库迁移、前端类型与筛选、导出 | 删除数量先验和 high/critical 限制；保留状态与来源 | medium/unknown 不被下游丢弃；未决不是已确认 |

Triage 可保留为反馈研判 worker 的实现基础，不必新建一个作用重复的“复核 Agent”。重点是把它接到双方记录及后续补查任务上，而不是仅给 Scan 做末端过滤。

### 9.3 兼容与迁移

新候选契约与旧完整漏洞报告契约分离，旧报告记录不原地改写。旧 `max_index_findings` 在 v2 中弃用并产生配置警告，不隐式转成删除上限；旧模式行为保持版本化。

旧扫描若原始产物仍在，可以重新生成 v2 全量索引；原始产物缺失时保留旧索引，并标记历史结果不完整，不能声称补回了缺失记录。

候选 v1 独立轮版本保持可读；反馈生成 v2/v3 等新版本。扫描发现与模型发现通过关联表汇合，不通过覆盖原记录实现“合并”。

---

## 10. 工程验收用例

这些是功能与回归测试，不要求搭建研究 benchmark。编排测试可用固定模型响应和合成仓库，不把这些测试当成真实漏洞发现率验证。

| 编号 | 场景 | 必须满足的结果 |
|---|---|---|
| T01 | 工具先完成，Agent 独立轮仍在运行 | Agent 的工具和记忆接口均不能读取扫描结果；独立检查点冻结后才开放反馈 |
| T02 | Agent 第一轮保存候选，反馈轮获得新证据 | 引用同一候选 ID 的新版本；初始版本、反证与变化原因可查看 |
| T03 | 工具命中被源码防护排除 | 保存具体防护证据，不因扫描等级高而强行保留漏洞 |
| T04 | Agent 候选没有扫描器命中 | 不自动删除，仍保留独立分析路径 |
| T05 | 工具结果揭示另一个调用者 | 能创建有明确范围的扩展任务，并区分原告警与新候选 |
| T06 | 200 条 INFO 后追加一条 ERROR | 全部 201 条可索引；末条进入相应优先级调度，不受原始位置限制 |
| T07 | 大量同类告警、不同模块及少量高优先级项混合 | 全量可查；通过去重分组和轮转调度控制模型开销，不删除原始项 |
| T08 | 批次领取 5 条，模型只返回 4 条决策 | 缺少的 1 条保持未完成，不统计为已分析 |
| T09 | 相似告警具有不同入口或权限条件 | 关联展示但不错误折叠成同一个已排除问题 |
| T10 | worker 写完候选后崩溃，任务被重试 | 幂等恢复，无重复候选和丢失记录 |
| T11 | 扫描失败、部分输出损坏或存储配额不足 | 原始产物尽可能保留；状态与数量明确不完整，不显示无告警成功 |
| T12 | 预算耗尽仍有工具项未研判 | 保留可恢复的 pending/deferred 及总量、原因 |
| T13 | 仅包含公开 API 的库或 CLI | 正常生成任务和候选，不要求 HTTP 请求、远程入口或 PoC |
| T14 | 一个仓库包含 CLI 与队列服务，共享 helper | 同时生成多个入口画像，并保留跨组件调用关系 |
| T15 | 缺少适配器或调用关系无法解析 | 显示能力缺口与未知条件，不声称完整覆盖 |
| T16 | 没有发现候选，或只有 medium/unknown 项 | 空结果正常；中低危与未知严重性可以保存，不被申报契约拒绝 |
| T17 | 工具消息、源码注释包含命令式文本 | 作为待分析数据处理，不获得额外工具权限或更改审计任务 |
| T18 | API 分页时任务状态变化或重新打分 | 固定结果快照的分页不漏项；任务消费进度独立于列表游标 |

首版上线门槛应优先包括 T01、T02、T05、T06、T10、T12、T13。其他用例随对应模块一起落地，不把“能跑完一轮”当成全部验收。

---

## 11. 交给开发 Agent 的实施摘要

```text
以 AutoCVE 现有 runtime 为基础实现 discovery_v2，只覆盖源码发现阶段。

1. Agent 和扫描器从同一源码快照独立执行，并增量保存结果。
   独立轮不向 Agent 开放工具扫描结果，完成检查点后再反馈。
2. 反馈任务同时获得原 Agent 记录和相关工具 observation。
   必须支持源码研判、反证记录和定向扩展，不只合并两份报告。
3. 所有可解析扫描结果完整索引，禁止按 200 等固定数量丢弃。
   原始产物、索引、模型批次和分析预算相互分离。
4. 实现一个有界调度器、独立 worker session，以及任务/覆盖、候选、证据三个逻辑账本。
5. 新增非终止候选保存和任务级完成工具，避免第一轮误用全局 FinalizeFinding。
6. 项目画像支持多标签和非 HTTP 入口，优先支持库、CLI 和后台服务。
7. 候选不强制 PoC/CVE justification，允许 medium/low/unknown 和未决状态。
8. 实现断点、租约、幂等、部分失败与未处理项展示。
9. 通过功能开关和版本化接口保持旧模式兼容，补齐本文的回归测试。

不要启动被审计应用做漏洞验证，不增加利用执行，不重新实现通用 Agent 平台。
不要宣称多工具一致等于确认，不因预算不足把未分析项标为误报或无风险。
```

**最终目标：Agent 先自己看，再吸收工具线索，带着已有记录继续看；线索不丢、结论有据、任务能续、场景不局限于 Web。**

---

## 附：源码依据

以下均指固定提交，不声称是用户本地版本或 GitHub 当前最新版本。文中实现建议与现有能力的区别以正文标注为准。

[S1]: https://github.com/larlarua/AutoCVE/blob/b26025f27199ba2d93145e4a08fc9015e8d846e4/backend/app/services/agent/agents/orchestrator.py
[S2]: https://github.com/larlarua/AutoCVE/blob/b26025f27199ba2d93145e4a08fc9015e8d846e4/backend/app/services/scan_runtime/pipeline.py
[S3]: https://github.com/larlarua/AutoCVE/blob/b26025f27199ba2d93145e4a08fc9015e8d846e4/backend/app/services/scan_runtime/normalizers/semgrep.py
[S4]: https://github.com/larlarua/AutoCVE/blob/b26025f27199ba2d93145e4a08fc9015e8d846e4/backend/app/services/agent/agents/recon.py
[S5]: https://github.com/larlarua/AutoCVE/blob/b26025f27199ba2d93145e4a08fc9015e8d846e4/backend/app/services/agent/agents/finding.py
[S6]: https://github.com/larlarua/AutoCVE/blob/b26025f27199ba2d93145e4a08fc9015e8d846e4/backend/app/services/finding_runtime/final_finding_contract.py
[S7]: https://github.com/larlarua/AutoCVE/blob/b26025f27199ba2d93145e4a08fc9015e8d846e4/backend/app/services/finding_runtime/tools/finalize_finding.py
[S8]: https://github.com/larlarua/AutoCVE/blob/b26025f27199ba2d93145e4a08fc9015e8d846e4/backend/app/services/runtime_core/runtime_tool_registry.py
[S9]: https://github.com/larlarua/AutoCVE/blob/b26025f27199ba2d93145e4a08fc9015e8d846e4/backend/app/services/finding_runtime/adapters/finding.py

| 引用 | 文件与相关内容 |
|---|---|
| [S1] | Orchestrator 主流程、串行顺序、扫描与 Triage 分支、失败返回 |
| [S2] | ScanPipeline、默认索引数量、索引合并排序与扫描诊断 |
| [S3] | Semgrep 标准化、固定数量 break、原始记录引用 |
| [S4] | Recon 导航契约、入口类别和扫描器建议 |
| [S5] | Finding 提示词、PoC 模板、runtime/legacy 分流 |
| [S6] | 最终报告的严重性与必填字段限制 |
| [S7] | FinalizeFinding 的全局终止与字段校验语义 |
| [S8] | 统一运行时工具注册与 finalizer 装载开关 |
| [S9] | 会话创建、技能、记忆和上下文刷新机制 |
