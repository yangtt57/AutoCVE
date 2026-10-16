# 专业 Skills 接入说明

适配版本：`2026.10.16.1`。按 `AutoCVE_专业Skills精选与接入建议_2026-10-16.md` 接入项目自身的技能库。

新增 **18 个适配包**：17 个用于综合静态审计的按需技能，1 个用于维护者导入审阅；Cloudflare 的 **10 个领域模块**保留在同一个包中。当前技能管理接口可见 22 个技能，包括原有 4 个。总计 35 份可读取的 Markdown 入口/参考文件。

## 使用

1. 在项目根目录运行 `./start.sh`，打开应用。
2. 新建 Agent 审计任务，保持“使用源码发现与覆盖账本”开启，选择项目和版本标记。
3. 系统从不可变源码快照识别语言、入口和领域，按工作包选择技能。无需在旧 Agent 绑定开关中逐个启用新技能。
4. Skills 页面显示“按场景选用”、适配版本、上游提交及许可；候选卡片的“使用的 Skills”显示实际阅读记录，可打开原文证据及行范围。JSONL 导出同时保留这些记录。

老任务沿用创建时的技能目录快照；安装本次适配之前的任务不会自动改写记录。要使用本次新增技能，请创建新任务。

## 已接入内容

| 适配包 | 使用条件与内容 |
|---|---|
| `autocve-code-audit` | Web/API 主方法，沿用原有 code-audit-finding 的入口、信任边界、对象授权方法，改为 v2 三态输出 |
| `autocve-context-building` | 非 Web 主方法；输入、隐式状态、调用前提、不变量、输出、失败路径和未知条件；附分析格式 |
| `autocve-variant-analysis` | 有真实源码证据的候选进入补查后，围绕原根因做有界变体追踪；不确定根因仍按假设处理 |
| `autocve-sharp-edges` | SDK、库、CLI 的正常调用、易误用接口、参数组合和安全默认值 |
| `autocve-insecure-defaults` | 配置优先级、备用密钥、默认身份与失败后放行；缺证据不会自动判为已排除 |
| `autocve-semgrep-feedback` | 扫描反馈阶段读取原始 observation，核对源码后逐项回执；不重复执行扫描 |
| `autocve-sarif-interpretation` | SARIF 语义、规则继承、定位与原始出现的解释；仅在反馈材料声明 SARIF 时路由，当前内置扫描器仍输出 Semgrep JSON |
| `autocve-native-c-review` | C/C++ 用户态程序、解析器和库；附按位置检查内存、整数、所有权和状态不变量的矩阵 |
| `autocve-rust-review` | safe/unsafe、FFI、布局、生命周期、panic、锁、异步与取消；附两个专项参考 |
| `autocve-django-access` | Django/DRF；装饰器、中间件、基类、权限类、queryset、Manager 和租户范围；附授权层参考 |
| `autocve-secret-serialization` | Python/JS/TS 凭据 holder → 序列化 → sink → 读者；附序列化路径对照；只有 holder 时不声称泄漏成立 |
| `autocve-gha-review` | GitHub Actions 的事件来源、表达式、checkout、token、缓存、产物和发布权限 |
| `autocve-agentic-actions` | 含 AI Agent 的 CI；不可信内容、动作绑定、工具 handler 与执行身份 |
| `autocve-supply-chain` | 依赖解析与发布消费链；版本公告、维护风险与当前可达缺陷分开；不联网查询或运行安装步骤 |
| `autocve-differential-review` | 显式提供变更路径和比较依据时，分析变更及其调用者影响，证据重新绑定当前快照 |
| `autocve-spec-compliance` | 显式提供独立规范路径与来源依据时，检查规范—实现对应；不从代码反推规范 |
| `autocve-cloudflare-domains` | 同一个领域包，按任务选择至多两个参考模块 |
| `autocve-skill-import-review` | 维护者使用的外部技能审阅参考，不绑定普通审计 worker；配套本地清单校验命令 |

Cloudflare 模块：AI/LLM、HTTP/认证、客户端、原生内存、云与部署、RPC/消息、资源与可用性、数据隔离/生命周期、供应链/发布、桌面/移动端/本地 IPC。

## 选择与读取边界

每个工作包选择 **1 个主方法 + 至多 1 个专项 + 至多 2 个领域参考**。目录元数据可以较大，模型上下文只收到选中项及读取路径；正文通过只读 `Skill` 工具按需读取。单次最多 200 行、14,000 字符，单文件最多 128 KiB，响应携带行范围与是否有后续内容。

路由使用工作包的入口文件与源码信号，而非整个仓库的所有框架标签。C/C++、Rust、CI、部署、IPC、依赖清单即使与 Web 代码共处一个模块，也能生成各自的工作包。识别为启发式，不增加解析器能力或自动声称覆盖完成。

独立轮无法借技能读取当前扫描结果；反馈轮才选择扫描解释技能；补查只有在候选存在真实源码支持时选择变体方法。优先级保证专项互斥，未选中的技能/参考不能通过该工具临时扩大加载范围。

完整上游归档作为离线资料保存。运行时只加载适配后的 Markdown，不解压归档，不运行上游脚本、hooks、测试、子代理、动态验证或报告流水线。既有 cve-report-writer 不绑定 discovery worker，旧会话技能机制保持原行为，新适配包不被启动过程自动绑定到旧用户会话。

## 可追溯记录

每次真实阅读将内容、SHA-256、目录快照哈希、提交、上游入口、适配文件、行范围、task/attempt 写入 `DiscoveryEvidence(kind=skill_reference)`，并与当前有效任务租约一起保存回执。只列目录不会产生“已读”记录。

候选版本的 `skills_used` 由服务端从阅读回执生成，包含：

- `skill_slug`、`upstream_repo`、`upstream_commit`、`entry_path`、`adaptation_version`、`license`；
- 实际读到的适配文件 `reference_paths`，对应的上游来源 `source_paths`；
- `tool_evidence_ids` 与逐次阅读的行范围、文件哈希、任务/尝试标识。

这里的上游路径表示适配依据，不声称模型读了完整上游原件。候选更新保留以前的使用记录和历史版本；续跑合并原检查点与新阅读回执。模型不能自行填入 `skills_used`。没有发生读取时字段为空，不能把安装或选中等同使用。

技能参考不得写入候选支持/反证、预期策略证据或覆盖证据字段。只有真实源码阅读才计入源码覆盖。篡改的文件、未列入清单的路径、符号链接、脚本以及越界路径会被拒绝。

## 规范与差异审计的可选 API 输入

创建任务时可在 `discovery_v2.skill_context` 中提供一种专项上下文，例如：

```json
{
  "discovery_v2": {
    "enabled": true,
    "skill_context": {
      "spec_paths": ["docs/protocol.md"],
      "spec_basis": "用户指定：此文件是本版本独立维护的协议契约"
    }
  }
}
```

差异审计对应 `changed_paths` 和 `comparison_basis`。比较依据可描述用户提供的差异及相关快照内材料；系统不会虚构或自动获取历史基线。所有路径必须存在于当前不可变快照，缺少依据会被拒绝。两种上下文都提供时规范专项优先。现有创建弹窗使用自动路由，未增加这组高级输入项。

## 固定来源与升级

| 来源 | 固定提交 | 许可 |
|---|---|---|
| [Trail of Bits](https://github.com/trailofbits/skills/tree/1f68e03536f7980d4c0e6869596f708043a19443) | `1f68e03536f7980d4c0e6869596f708043a19443` | CC-BY-SA-4.0 |
| [Cloudflare](https://github.com/cloudflare/security-audit-skill/tree/c1c8a8c1471069fb0e188eeaff69b8e8db6564a8) | `c1c8a8c1471069fb0e188eeaff69b8e8db6564a8` | MIT |
| [Sentry](https://github.com/getsentry/skills/tree/f57ada2d0b640406ea7e25b11d636c530e77c58b) | `f57ada2d0b640406ea7e25b11d636c530e77c58b` | Apache-2.0；Django 参考保留 OWASP CC-BY-SA-4.0 |

原件、许可证在 `skill_sources/<来源>/<提交>/`；归档固定哈希在 `skills_sources_manifest.json`；加载清单在 `skill_library/.discovery/manifest.json`；每个适配包包含 `metadata.json`、`NOTICE.md` 和适用许可文本。许可与派生内容约束只针对对应第三方材料，未改写项目其他代码的许可。

```bash
# 离线校验文件、来源、许可、链接、权限声明和内容哈希
python3 scripts/manage_audit_skills.py verify

# 仅补回缺少且匹配固定哈希的原始归档
python3 scripts/manage_audit_skills.py fetch
```

升级时先审阅新的固定提交及实际改动，再更新适配正文、来源说明、版本和清单哈希。不要将分支名换作提交，不要仅修改正文后绕过哈希校验。修改清单与包元数据后重新校验，并新建审计任务；已有任务仍绑定旧哈希。

## 范围与验证

按建议暂不启用完整 fp-check、CodeQL 构建/查询、Semgrep 规则生成执行、fuzz、sanitizer、二进制、恒定时间与专门零化验证。移动端/内核资料的存在不表示新增 APK、内核、驱动或固件分析后端。当前新增能力是静态审计方法与路由。

已验证：固定归档与 35 份入口/参考完整性；各类源码路由、任务阶段隔离、混合项目工作包、真实 Skill 工具到候选的记录、历史版本与续跑、路径/篡改/过期租约拒绝、技能不得作为代码覆盖证据、既有技能/API 兼容；前端生产构建通过。

本次不以真实项目调用模型评估检出率，也未运行上游归档中的脚本或测试。测试中的固定模型用于核对运行链路，不代表真实模型审计效果。

2026-10-17 更新：此前记录的 TypeScript 类型问题已修复，`npm run type-check` 检查完整配置范围并通过，前端生产构建通过。上游 `skillsManagerPaths.test.ts` 的两项源码文本断言仍与既有实现不一致，未纳入所选通过项；它们不验证运行时技能读取结果。
