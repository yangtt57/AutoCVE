# AutoCVE 专业 Skills 精选与接入建议

> 设计背景文档（2026-10-16），保留当时的规划与来源核对。部分内容已落地，当前功能和安装方法以 [README](README.md)、[改动清单](docs/FORK_CHANGES.md) 及对应功能文档为准。

核对日期：**2026-10-16**。目标：在 AutoCVE 骨架上增强实用、多场景的**第一阶段源码审计**。

**结论：优先引入 Trail of Bits 的专项方法、Cloudflare 的多场景参考，以及 Sentry 的少数框架/数据泄露技能。不是把所有安全技能塞进一个提示词。**

本目录收录 **33 个可复用单元**：包括独立技能入口、带工作流的插件、同一技能内的参考模块。**不等于 33 个独立可直接安装的 skills。** 共来自三个主来源；Cloudflare 的一个父技能及其十个领域文件分别列出，便于路由，不表示十一个独立安装包。

本次核对了仓库目录、README、默认分支近期提交，并阅读了重点技能正文或正文前段。逐项阅读深度见目录及 JSON。没有安装到你的 AutoCVE，没有下载完整上游技能源文件包，也没有运行全部脚本或进行兼容性测试。

## 1. AutoCVE 自带的技能真的少吗？

本次查看的公开 `skill_library/` 中，排除 `.runtime` 和 `agents` 后，有四个顶层技能包：`code-audit-finding`、`code-security`、`cve-report-writer`、`secknowledge-skill`。这不是你的本地安装清单。[A1]

`code-audit-finding` 内含语言、框架、污点分析、覆盖与误报相关参考；`code-security` 文档声称覆盖 15+ 语言和 28 类规则，包含 C/C++、容器和基础设施配置。因此更准确的判断是：**顶层包少，但通用知识并非空白；更值得补专业深度、场景触发与结果契约。** `cve-report-writer` 不应绑定当前发现 worker；`secknowledge-skill` 自身也区分测试和完整白盒审计的触发范围。[A2][A3][A4]

## 2. 主来源：关注度、近期维护与采用信号

以下 Stars/Forks 为检索快照，不能解释为用户数、安装量或审计效果。提交时间统一为 UTC；是仓库主分支最新提交，不代表每个安全技能都在该日更新。

| 来源 | Stars / Forks | 核对到的主分支提交时间（UTC） | 定位 |
|---|---|---|---|
| [trailofbits/skills](https://github.com/trailofbits/skills) | 7,567 / 648 | [2026-10-15T14:34:14Z](https://github.com/trailofbits/skills/commit/1f68e03536f7980d4c0e6869596f708043a19443) | 通用审计方法与语言/工具专项 |
| [cloudflare/security-audit-skill](https://github.com/cloudflare/security-audit-skill) | 约 29.8k / 约 1.8k | [2026-09-14T19:28:54Z](https://github.com/cloudflare/security-audit-skill/commit/c1c8a8c1471069fb0e188eeaff69b8e8db6564a8) | 统一源码审计方法与多场景领域参考 |
| [getsentry/skills](https://github.com/getsentry/skills) | 约 1.1k / 55 | [2026-10-15T13:25:46Z](https://github.com/getsentry/skills/commit/f57ada2d0b640406ea7e25b11d636c530e77c58b) | 开发团队使用的框架、CI 与秘密泄露专项 |

Cloudflare README 说明该 skill 是其内部漏洞发现系统的起点；Sentry 仓库说明这些技能用于团队开发。它们提供了比单纯 Stars 更具体、但仍属于维护方自述的采用信息。Trail of Bits 的来源、专项内容和维护活动使其适合重点筛选；这里不声称掌握任一仓库的实际使用人数。[C1][S1][T1]

仓库许可证分别为 Trail of Bits 的 CC-BY-SA-4.0、Cloudflare 的 MIT、Sentry 的 Apache-2.0；Sentry 部分安全参考另注明 OWASP CC-BY-SA-4.0。引入时保留来源、许可证和修改记录，并逐文件检查第三方材料声明；不要把仓库顶层许可证当作所有依赖材料的唯一声明。[T1][C1][S2]

## 3. Trail of Bits：专项技能主库

P0 表示建议首批适配；P1 表示按项目场景启用；P2 表示后续专项；DEFER 表示当前不要原样运行。优先级是本方案的工程建议，不是实测排名。

### audit-context-building

**优先级：P0；形态：`skill_with_workflow`。**

来源：[trailofbits/skills / plugins/audit-context-building](https://github.com/trailofbits/skills/tree/1f68e03536f7980d4c0e6869596f708043a19443/plugins/audit-context-building)

用途：逐函数整理输入约束、调用关系、假设和未知条件，为源码审计建立上下文。

适用场景：all_source。建议阶段：recon, context_enrichment。

**接入注意：**提取分析格式和领域参考；将其 Workflow/Task 交给 AutoCVE 调度器。只分析相关范围，不默认对所有函数启动子代理。

已识别的入口：`plugins/audit-context-building/skills/audit-context-building/SKILL.md`。

核对深度：已阅读 SKILL 正文；正文来自 main，部署前应对固定提交复核。

### variant-analysis

**优先级：P0；形态：`skill_with_workflow`。**

来源：[trailofbits/skills / plugins/variant-analysis](https://github.com/trailofbits/skills/tree/1f68e03536f7980d4c0e6869596f708043a19443/plugins/variant-analysis)

用途：从一个已有依据的根因出发，逐步扩展匹配模式，寻找其他调用点或相似缺陷。

适用场景：all_source。建议阶段：feedback, followup。

**接入注意：**扫描命中不自动成为已证实根因。未闭合根因及其变体都保留为假设；限制扩展轮数，复用候选去重记录。

已识别的入口：`plugins/variant-analysis/skills/variant-analysis/SKILL.md`。

核对深度：已阅读固定提交 SKILL 正文。

### sharp-edges

**优先级：P0；形态：`skill_with_references`。**

来源：[trailofbits/skills / plugins/sharp-edges](https://github.com/trailofbits/skills/tree/1f68e03536f7980d4c0e6869596f708043a19443/plugins/sharp-edges)

用途：检查 API 易误用设计、危险配置组合和不安全默认路径。

适用场景：library, sdk, configuration, crypto_api。建议阶段：independent, feedback。

**接入注意：**设计风险与可达漏洞分别输出；API 容易误用不等于库自身存在可利用漏洞。

已识别的入口：`plugins/sharp-edges/skills/sharp-edges/SKILL.md`。

核对深度：已阅读固定提交 SKILL 正文前段。

### insecure-defaults

**优先级：P0；形态：`plugin_workflow_not_standalone_skill`。**

来源：[trailofbits/skills / plugins/insecure-defaults](https://github.com/trailofbits/skills/tree/1f68e03536f7980d4c0e6869596f708043a19443/plugins/insecure-defaults)

用途：追踪缺省配置、回退密钥、默认凭据、失效开放开关及其实际使用路径。

适用场景：configuration, cli, daemon, web, library。建议阶段：independent, feedback。

**接入注意：**当前目录是 commands/references/workflows，而非可直接导入的同名 SKILL。提取领域知识；不得照搬“链不完整即 refuted”规则，缺证据应记 needs_context。移除固定模型和多层编排。

核对深度：已核对固定提交目录并阅读 README 前段。

### c-review

**优先级：P1；形态：`skill_with_workflow`。**

来源：[trailofbits/skills / plugins/c-review](https://github.com/trailofbits/skills/tree/1f68e03536f7980d4c0e6869596f708043a19443/plugins/c-review)

用途：原生用户态程序的内存安全、整数问题、竞争与平台相关审计。

适用场景：c, cpp, parser, userspace_daemon, native_library。建议阶段：independent, feedback。

**接入注意：**需要整个插件的 workflow、prompts、scripts，不是只复制入口文件。映射到现有 worker；原版明确不覆盖内核/驱动和无 libc 裸机。

已识别的入口：`plugins/c-review/skills/c-review/SKILL.md`。

核对深度：已阅读固定提交 SKILL 正文前段。

### rust-review

**优先级：P1；形态：`skill_with_workflow`。**

来源：[trailofbits/skills / plugins/rust-review](https://github.com/trailofbits/skills/tree/1f68e03536f7980d4c0e6869596f708043a19443/plugins/rust-review)

用途：Rust 安全/unsafe 边界、FFI、并发、panic 可达性和异步逻辑审计。

适用场景：rust, library, daemon, ffi, async。建议阶段：independent, feedback。

**接入注意：**保留任务与上下文范围分离，改写 Task/Agent/SendMessage 等宿主协议。不是合约通用检查器；敏感数据清零由单独专项承担。

已识别的入口：`plugins/rust-review/skills/rust-review/SKILL.md`。

核对深度：已阅读固定提交 SKILL 正文前段。

### differential-review

**优先级：P1；形态：`plugin_catalog_entry`。**

来源：[trailofbits/skills / plugins/differential-review](https://github.com/trailofbits/skills/tree/1f68e03536f7980d4c0e6869596f708043a19443/plugins/differential-review)

用途：从代码变更及相关历史出发进行安全差异审查。

适用场景：all_source, incremental_audit。建议阶段：incremental。

**接入注意：**用于增量任务；变更集不是读取上下文的边界；旧结论绑定源码版本，不替代全量审计。

核对深度：目录/README 已核对，正文未逐项审读。

### spec-to-code-compliance

**优先级：P1；形态：`skill_with_workflow`。**

来源：[trailofbits/skills / plugins/spec-to-code-compliance](https://github.com/trailofbits/skills/tree/1f68e03536f7980d4c0e6869596f708043a19443/plugins/spec-to-code-compliance)

用途：把权威文档中的要求逐项对应到实现，保留部分实现、矛盾与无法判断的情况。

适用场景：protocol, library, state_machine, firmware, service。建议阶段：independent, feedback。

**接入注意：**需要独立、可信的规范依据；不能从同一段实现反推出规则后再声称实现符合规则。非安全语义差异不自动标漏洞。

已识别的入口：`plugins/spec-to-code-compliance/skills/spec-to-code-compliance/SKILL.md`。

核对深度：已阅读 SKILL 正文；正文来自 main，部署前应对固定提交复核。

### sarif-parsing

**优先级：P0；形态：`skill_in_multi_skill_plugin`。**

来源：[trailofbits/skills / plugins/static-analysis](https://github.com/trailofbits/skills/tree/1f68e03536f7980d4c0e6869596f708043a19443/plugins/static-analysis)

用途：解释 SARIF 输出、规则继承字段、定位和来源关系。

适用场景：multi_language_source。建议阶段：feedback。

**接入注意：**索引入库、分页和去重必须由确定性代码实现；skill 不能修复 AutoCVE 的 200 条截断。

核对深度：已阅读固定提交插件 README；未逐项审读这三个 SKILL 正文。

### semgrep

**优先级：P1；形态：`skill_in_multi_skill_plugin`。**

来源：[trailofbits/skills / plugins/static-analysis](https://github.com/trailofbits/skills/tree/1f68e03536f7980d4c0e6869596f708043a19443/plugins/static-analysis)

用途：选择规则、解释匹配与污点分析结果，辅助规则扫描规划。

适用场景：multi_language_source。建议阶段：scan_planning, feedback。

**接入注意：**扫描执行由 ScanPipeline 统一拥有；独立模型轮不读取扫描结果，也不重复启动相同扫描。

核对深度：已阅读固定提交插件 README；未逐项审读这三个 SKILL 正文。

### codeql

**优先级：P2；形态：`skill_in_multi_skill_plugin`。**

来源：[trailofbits/skills / plugins/static-analysis](https://github.com/trailofbits/skills/tree/1f68e03536f7980d4c0e6869596f708043a19443/plugins/static-analysis)

用途：为跨过程数据流分析准备数据库、查询和项目自定义模型。

适用场景：multi_language_source。建议阶段：scan_planning, feedback。

**接入注意：**必须实际具备工具与语言适配；构建步骤有副作用，需独立沙箱和授权策略。当前首版可暂不启用。

核对深度：已阅读固定提交插件 README；未逐项审读这三个 SKILL 正文。

### semgrep-rule-creator

**优先级：P1；形态：`plugin_catalog_entry`。**

来源：[trailofbits/skills / plugins/semgrep-rule-creator](https://github.com/trailofbits/skills/tree/1f68e03536f7980d4c0e6869596f708043a19443/plugins/semgrep-rule-creator)

用途：将有明确语义的模式形成项目专用 Semgrep 检查规则。

适用场景：multi_language_source。建议阶段：feedback, followup。

**接入注意：**先核对根因；新规则须以正负样例检查并由扫描适配器接管。不能让模型直接生成命令后把成功叙述当运行证据。

核对深度：目录/README 已核对，正文未逐项审读。

### supply-chain-risk-auditor

**优先级：P1；形态：`plugin_catalog_entry`。**

来源：[trailofbits/skills / plugins/supply-chain-risk-auditor](https://github.com/trailofbits/skills/tree/1f68e03536f7980d4c0e6869596f708043a19443/plugins/supply-chain-risk-auditor)

用途：分析依赖版本对应公告、维护风险、发布方与安装脚本风险。

适用场景：npm, pypi, go, dependencies。建议阶段：independent, feedback。

**接入注意：**版本公告、上游维护风险、当前应用可达漏洞分栏展示；联网查询经工具代理，不执行不可信安装脚本。

核对深度：目录/README 已核对，正文未逐项审读。

### agentic-actions-auditor

**优先级：P1；形态：`plugin_catalog_entry`。**

来源：[trailofbits/skills / plugins/agentic-actions-auditor](https://github.com/trailofbits/skills/tree/1f68e03536f7980d4c0e6869596f708043a19443/plugins/agentic-actions-auditor)

用途：针对调用 AI Agent 的 GitHub Actions 审计不可信内容与权限边界。

适用场景：github_actions, ai_agent, ci。建议阶段：independent, feedback。

**接入注意：**按工作流事件、输入来源、token 权限和工具能力选择任务；不执行 CI、不启用远端写操作。

核对深度：目录/README 已核对，正文未逐项审读。

### constant-time-analysis

**优先级：P2；形态：`plugin_catalog_entry`。**

来源：[trailofbits/skills / plugins/constant-time-analysis](https://github.com/trailofbits/skills/tree/1f68e03536f7980d4c0e6869596f708043a19443/plugins/constant-time-analysis)

用途：提供密码实现与编译相关时间侧信道分析方向。

适用场景：crypto, native。建议阶段：specialized_static。

**接入注意：**源码分支检查只是线索；二进制/编译器分析与测量部分另行接入，不能声称源码阅读证明恒定时间。

核对深度：目录/README 已核对，正文未逐项审读。

### zeroize-audit

**优先级：P2；形态：`plugin_catalog_entry`。**

来源：[trailofbits/skills / plugins/zeroize-audit](https://github.com/trailofbits/skills/tree/1f68e03536f7980d4c0e6869596f708043a19443/plugins/zeroize-audit)

用途：检查敏感值清零缺失或被编译优化消除的风险。

适用场景：c, cpp, rust, crypto。建议阶段：specialized_static。

**接入注意：**先采用源码与生命周期检查；未进行编译后检查时保留局限，不生成确定的运行时结论。

核对深度：目录/README 已核对，正文未逐项审读。

### fp-check

**优先级：DEFER_FULL_WORKFLOW；形态：`skill_with_workflow`。**

来源：[trailofbits/skills / plugins/fp-check](https://github.com/trailofbits/skills/tree/1f68e03536f7980d4c0e6869596f708043a19443/plugins/fp-check)

用途：提供特定漏洞命题、调用者、控制措施和反证检查方法。

适用场景：all_source。建议阶段：feedback_static_excerpt_only。

**接入注意：**完整技能包含验证流程及二元判定，不符合当前不做动态验证的范围。只能提取源码复核部分，并保留 needs_context；不是新漏洞发现器。

已识别的入口：`plugins/fp-check/skills/fp-check/SKILL.md`。

核对深度：已阅读固定提交 SKILL 正文前段。

## 4. Cloudflare：补齐非 Web 场景的主要来源

上游是一套 `security-audit` 技能，附多个主题 Markdown。建议保留一个来源包，并由 AutoCVE 的场景路由读取其中少量文件，而不是把每份参考都安装成互相竞争的全局技能。[C1]

### security-audit

**优先级：P0；形态：`skill_with_reference_modules`。**

来源：[cloudflare/security-audit-skill / skills/security-audit](https://github.com/cloudflare/security-audit-skill/tree/c1c8a8c1471069fb0e188eeaff69b8e8db6564a8/skills/security-audit)

用途：组织架构理解、覆盖驱动任务和有依据的候选记录，附带多场景审计参考。

适用场景：all_source。建议阶段：recon, independent, feedback。

**接入注意：**原版完整流程含验证和报告；为 AutoCVE 单独编写 static-only 适配入口，仅路由所需方法与领域参考。不要启用第二套完整编排或继承 confirmed 判定。

已识别的入口：`skills/security-audit/SKILL.md`。

核对深度：已阅读 SKILL、固定提交 README，并抽查领域正文。

### memory-safety-and-binary

**优先级：P1；形态：`reference_module_not_standalone_skill`。**

来源：[cloudflare/security-audit-skill / skills/security-audit/MEMORY-SAFETY-AND-BINARY.md](https://github.com/cloudflare/security-audit-skill/blob/c1c8a8c1471069fb0e188eeaff69b8e8db6564a8/skills/security-audit/MEMORY-SAFETY-AND-BINARY.md)

用途：原生目标的内存安全与二进制相关检查方向。

适用场景：c, cpp, native, parser。建议阶段：independent, feedback。

**接入注意：**内核/二进制参考存在不等于 AutoCVE 已具备相应分析后端。

核对深度：固定提交 README 确认文件及主题；未完整审读该领域正文。

### ai-and-llm

**优先级：P1；形态：`reference_module_not_standalone_skill`。**

来源：[cloudflare/security-audit-skill / skills/security-audit/AI-AND-LLM.md](https://github.com/cloudflare/security-audit-skill/blob/c1c8a8c1471069fb0e188eeaff69b8e8db6564a8/skills/security-audit/AI-AND-LLM.md)

用途：LLM 应用中的不可信输入、工具调用和输出处理边界。

适用场景：ai_agent, llm, tool_gateway。建议阶段：independent, feedback。

**接入注意：**仅检查应用与工具边界；不运行注入攻击或越权工具调用。

核对深度：固定提交 README 确认文件及主题；未完整审读该领域正文。

### web-protocol-and-auth

**优先级：P1；形态：`reference_module_not_standalone_skill`。**

来源：[cloudflare/security-audit-skill / skills/security-audit/WEB-PROTOCOL-AND-AUTH.md](https://github.com/cloudflare/security-audit-skill/blob/c1c8a8c1471069fb0e188eeaff69b8e8db6564a8/skills/security-audit/WEB-PROTOCOL-AND-AUTH.md)

用途：HTTP 解析、缓存与认证协议边界。

适用场景：web, api, proxy, http。建议阶段：independent, feedback。

**接入注意：**普通鉴权规则与跨组件协议差异分别记录；未见部署组件时记未知。

核对深度：固定提交 README 确认文件及主题；未完整审读该领域正文。

### client-side

**优先级：P1；形态：`reference_module_not_standalone_skill`。**

来源：[cloudflare/security-audit-skill / skills/security-audit/CLIENT-SIDE.md](https://github.com/cloudflare/security-audit-skill/blob/c1c8a8c1471069fb0e188eeaff69b8e8db6564a8/skills/security-audit/CLIENT-SIDE.md)

用途：客户端 DOM、消息来源信任、原型污染及界面相关边界。

适用场景：browser, frontend, webview。建议阶段：independent, feedback。

**接入注意：**只读源码部分；浏览器测试和点击交互不在本阶段执行。

核对深度：固定提交 README 确认文件及主题；未完整审读该领域正文。

### supply-chain-and-release

**优先级：P1；形态：`reference_module_not_standalone_skill`。**

来源：[cloudflare/security-audit-skill / skills/security-audit/SUPPLY-CHAIN-AND-RELEASE.md](https://github.com/cloudflare/security-audit-skill/blob/c1c8a8c1471069fb0e188eeaff69b8e8db6564a8/skills/security-audit/SUPPLY-CHAIN-AND-RELEASE.md)

用途：依赖、构建、发布、签名、更新和扩展机制。

适用场景：ci, release, dependencies, plugin。建议阶段：independent, feedback。

**接入注意：**不把所有未固定版本都等同可利用漏洞；保留部署条件。

核对深度：固定提交 README 确认文件及主题；未完整审读该领域正文。

### cloud-and-deployment

**优先级：P0；形态：`reference_module_not_standalone_skill`。**

来源：[cloudflare/security-audit-skill / skills/security-audit/CLOUD-AND-DEPLOYMENT.md](https://github.com/cloudflare/security-audit-skill/blob/c1c8a8c1471069fb0e188eeaff69b8e8db6564a8/skills/security-audit/CLOUD-AND-DEPLOYMENT.md)

用途：IAM、基础设施代码、容器与部署配置。

适用场景：cloud, iac, container, serverless。建议阶段：independent, feedback。

**接入注意：**仓库看不见的真实云权限不能猜测；不访问或修改云账号。

核对深度：固定提交 README 确认文件及主题；未完整审读该领域正文。

### protocols-rpc-and-messaging

**优先级：P0；形态：`reference_module_not_standalone_skill`。**

来源：[cloudflare/security-audit-skill / skills/security-audit/PROTOCOLS-RPC-AND-MESSAGING.md](https://github.com/cloudflare/security-audit-skill/blob/c1c8a8c1471069fb0e188eeaff69b8e8db6564a8/skills/security-audit/PROTOCOLS-RPC-AND-MESSAGING.md)

用途：消息身份、租户字段、重放、顺序、确认与持久化、幂等性。

适用场景：rpc, queue, webhook, daemon。建议阶段：independent, feedback。

**接入注意：**区分 broker 保证与应用保证；未见 broker ACL、版本行为时保留未知。

核对深度：已阅读固定提交领域正文前段。

### resource-exhaustion-and-availability

**优先级：P1；形态：`reference_module_not_standalone_skill`。**

来源：[cloudflare/security-audit-skill / skills/security-audit/RESOURCE-EXHAUSTION-AND-AVAILABILITY.md](https://github.com/cloudflare/security-audit-skill/blob/c1c8a8c1471069fb0e188eeaff69b8e8db6564a8/skills/security-audit/RESOURCE-EXHAUSTION-AND-AVAILABILITY.md)

用途：共享资源、队列、worker 配额与计算资源预算。

适用场景：parser, daemon, queue, cli。建议阶段：independent, feedback。

**接入注意：**缺上限是线索；需说明输入控制和资源影响条件；不执行负载测试。

核对深度：固定提交 README 确认文件及主题；未完整审读该领域正文。

### data-isolation-and-lifecycle

**优先级：P0；形态：`reference_module_not_standalone_skill`。**

来源：[cloudflare/security-audit-skill / skills/security-audit/DATA-ISOLATION-AND-LIFECYCLE.md](https://github.com/cloudflare/security-audit-skill/blob/c1c8a8c1471069fb0e188eeaff69b8e8db6564a8/skills/security-audit/DATA-ISOLATION-AND-LIFECYCLE.md)

用途：数据隔离、缓存、检索、导出、备份、迁移、删除与恢复。

适用场景：multi_tenant, storage, export, backup。建议阶段：independent, feedback。

**接入注意：**梳理主体—对象—操作—生命周期；不能仅依赖路由层是否有登录装饰器。

核对深度：固定提交 README 确认文件及主题；未完整审读该领域正文。

### desktop-mobile-and-local-ipc

**优先级：P1；形态：`reference_module_not_standalone_skill`。**

来源：[cloudflare/security-audit-skill / skills/security-audit/DESKTOP-MOBILE-AND-LOCAL-IPC.md](https://github.com/cloudflare/security-audit-skill/blob/c1c8a8c1471069fb0e188eeaff69b8e8db6564a8/skills/security-audit/DESKTOP-MOBILE-AND-LOCAL-IPC.md)

用途：本地应用、深链接、WebView、导出组件、辅助进程和 IPC。

适用场景：desktop, mobile_source, ipc, privileged_helper。建议阶段：independent, feedback。

**接入注意：**需要相应平台源码与权限模型；不声称已支持纯 APK/固件/二进制黑盒审计。

核对深度：固定提交 README 确认文件及主题；未完整审读该领域正文。

## 5. Sentry：挑选精细专项，不整体照搬排除规则

通用 security-review 与现有方法重叠较大；Django 权限和秘密序列化更适合作为专项补充。原版规则包含影响报告范围的工程取舍，必须按你的审计威胁模型调整。[S2][S3][S4]

### django-access-review

**优先级：P1；形态：`skill_with_references`。**

来源：[getsentry/skills / skills/django-access-review](https://github.com/getsentry/skills/tree/f57ada2d0b640406ea7e25b11d636c530e77c58b/skills/django-access-review)

用途：梳理权限装饰器、中间件、基类、queryset、Manager、对象归属和租户过滤。

适用场景：python, django, drf, web。建议阶段：independent, feedback。

**接入注意：**只在 Django/DRF 命中时路由；登录不能代替对象授权。用于整仓时取消只看 diff 的范围假设。

已识别的入口：`skills/django-access-review/SKILL.md`。

核对深度：已阅读固定提交 SKILL 正文前段。

### secret-serialization

**优先级：P1；形态：`skill_with_references`。**

来源：[getsentry/skills / skills/secret-serialization](https://github.com/getsentry/skills/tree/f57ada2d0b640406ea7e25b11d636c530e77c58b/skills/secret-serialization)

用途：追踪凭据字段如何经对象序列化流入日志、trace、错误上报、缓存或响应。

适用场景：python, javascript, typescript, library, daemon。建议阶段：independent, feedback。

**接入注意：**区分潜在可序列化字段与真实泄露路径；单独字段风险不能直接升级为已确认泄露。按实际类型和序列化配置复核参考规则。

已识别的入口：`skills/secret-serialization/SKILL.md`。

核对深度：已阅读固定提交 SKILL 正文前段。

### gha-security-review

**优先级：P1；形态：`skill_catalog_entry`。**

来源：[getsentry/skills / skills/gha-security-review](https://github.com/getsentry/skills/tree/f57ada2d0b640406ea7e25b11d636c530e77c58b/skills/gha-security-review)

用途：GitHub Actions 工作流安全审查。

适用场景：github_actions, ci。建议阶段：independent, feedback。

**接入注意：**适配任务事件、权限与不可信输入，默认不执行工作流或访问秘密。

核对深度：目录/README 已核对，正文未逐项审读。

### security-review

**优先级：P2；形态：`skill_with_references`。**

来源：[getsentry/skills / skills/security-review](https://github.com/getsentry/skills/tree/f57ada2d0b640406ea7e25b11d636c530e77c58b/skills/security-review)

用途：提供通用源码审计的框架防护、配置与调用上下文检查。

适用场景：web, api, infrastructure, multi_language_source。建议阶段：independent, feedback。

**接入注意：**存在将需要认证的路径列入排除项的原版规则，必须删除；可信配置也应按具体威胁模型判断。与现有 code-audit-finding 高度重叠，不宜默认双主流程。

已识别的入口：`skills/security-review/SKILL.md`。

核对深度：已阅读固定提交 SKILL 正文前段。

### skill-scanner

**优先级：P1；形态：`skill_catalog_entry`。**

来源：[getsentry/skills / skills/skill-scanner](https://github.com/getsentry/skills/tree/f57ada2d0b640406ea7e25b11d636c530e77c58b/skills/skill-scanner)

用途：辅助检查外部导入的 skill 内容和风险。

适用场景：skill_supply_chain。建议阶段：import_review。

**接入注意：**检查通过不构成安全保证；脚本、hooks、下载地址和权限仍需显式审查与运行时约束。

核对深度：目录/README 已核对，正文未逐项审读。

## 6. 直接对应到你的多场景 worker

这是建议配置，不代表现有 AutoCVE 已经实现这些适配器。

| 项目信号 | 通用方法 | 建议加载的专项 | 不应该默认做的事 |
|---|---|---|---|
| Web / API / 多租户 | 保留现有 code-audit-finding，补充上下文方法 | Cloudflare 数据隔离、HTTP/Auth；Django 命中时加 django-access-review | 用登录状态替代对象权限分析 |
| 库 / SDK / CLI | audit-context-building | sharp-edges、insecure-defaults；Python/JS 凭据对象加 secret-serialization | 将正常网络/文件 API 能力自动等同漏洞 |
| 后台服务 / 队列 / RPC | audit-context-building | RPC/Messaging、Resource Exhaustion、Data Lifecycle | 假设“内部网络”天然可信，或猜测仓库外 broker ACL |
| C/C++ 库、解析器、用户态守护进程 | 上下文＋构建/调用信息 | c-review、Memory Safety；有密码场景再加 zeroize | 宣称仅凭一套提示词就覆盖所有内核、固件和二进制 |
| Rust 服务 / crate | 上下文＋项目画像 | rust-review；密码生命周期需要另加 zeroize | 把安全 Rust 等同于无拒绝服务或无逻辑问题 |
| 容器 / 云 / IaC / CI | 配置与信任边界画像 | Cloud/Deployment、Supply Chain；GitHub Actions 按需加 Sentry/TOB 专项 | 访问生产账号、执行部署或把配置缺省当运行现状 |
| AI Agent / 工具网关 | 应用与工具边界画像 | AI/LLM；在 CI 中运行 Agent 时加 agentic-actions-auditor | 执行攻击样例、打开额外工具权限 |
| 桌面 / 本地辅助服务 / 移动源码 | 主体与本地权限边界画像 | Desktop/Mobile/Local IPC | 将领域清单存在等同具备反编译或模拟器能力 |

## 7. 接到“先独立、后反馈”的综合审计流程

### 7.1 Recon / 上下文阶段

选择一个主方法，先整理组件、入口、主体、资源、公共校验、默认配置与未知条件。`audit-context-building` 适合提供分析格式，Cloudflare 的 RECONNAISSANCE 可补充场景覆盖。不能让两套原版多代理编排同时控制流程。

### 7.2 独立发现阶段

各 worker 只加载该任务需要的语言或领域内容，不读本次扫描告警。扫描工具独立运行并全量保存结果。专业 skill 可以读源码，不应绕过独立性要求再启动同一批工具扫描。

默认建议每个 worker 激活：**一个主方法＋一个语言专项＋一至两个领域参考**。这是控制上下文的起始建议，不是经过实验确定的上限。技能目录可以多，单任务激活集应小；大文件按索引再读相关章节。

### 7.3 反馈分析阶段

模型按任务领取扫描项，读取原来的候选、排除理由和代码证据，再检查输入控制、真实调用者、默认值与安全措施。SARIF 技能可辅助解释产物，但告警索引仍由程序保证全量、分页和可恢复。

得到有依据的根因之后，才调用 `variant-analysis`，沿其他调用点、相邻接口、共享组件或其他配置继续搜索。若根因尚不确定，只能记录“基于假设的扩展线索”，不能把其变体批量变成确认漏洞。

`fp-check` 的源码命题和反证检查可以作为适配材料，但本阶段不运行它的完整验证流程。原版“必须二元真假结论”的要求也不能移入当前契约。

### 7.4 持久记录

每个 candidate 保存 `skills_used`：来源仓库、固定 commit、入口文件、实际阅读的参考路径、适配版本与对应工具证据。阅读了 skill 不等于审计覆盖已完成；读了案例不等于被审计项目存在同样漏洞。

## 8. 需要改写的关键规则

**宿主依赖。** TOB 的 c-review、rust-review、audit-context-building 等含 Workflow、Task、Agent、模型名、脚本路径或子代理协议。AutoCVE 有自己的运行时；提取知识和检查任务，或者明确实现适配器，不能只替换工具名称后声称可用。

**结果语义。** `sharp-edges` 主要发现易误用设计；`secret-serialization` 也允许报告尚未追到 sink 的字段风险。这类结果应该进入设计风险/待补上下文类别，而不是直接作为已确认漏洞。

**排除规则。** Sentry 的 security-review 把需要预先认证才能到达的路径列入 Do Not Flag；不能照搬，因为认证后的越权仍属于你的目标。其服务器配置默认可信的假设也必须按 CLI、插件、本地权限等具体威胁模型重审。[S2]

**不完整不是已排除。** insecure-defaults 原文有“incomplete trace = refuted”的判定。你的候选契约应改为缺证据时 `needs_context`，有明确阻断依据才 `ruled_out`。该修改需标为你自己的适配版本，而非冒充上游原版语义。[T2]

**验证范围。** Cloudflare 原版完整流程以及 TOB fp-check 会进入候选验证。只读源码版本必须有独立入口和输出契约，不是原样运行后忽略某些步骤；不得输出未执行的确认结果。

**权限与安全。** 外部 skills、hooks、脚本、测试样例均按未信任内容处理。只读源码、联网代理、构建权限、写入产物目录与执行配额由运行时代码强制限制，不依赖 skill 中的自律声明。导入不自动执行安装脚本，也不自动更新远端 main。工具或资源不存在要报缺失，不允许模型假装执行。

## 9. 接入目录与版本管理建议

保留上游来源包和本地适配入口两层，例如：

```text
skill_sources/                    # 可信运营流程下载；不对目标仓库开放修改
  trailofbits/<commit>/...
  cloudflare/<commit>/...
  sentry/<commit>/...
skill_library/                    # AutoCVE 可发现的适配入口
  autocve-context-building/SKILL.md
  autocve-variant-analysis/SKILL.md
  autocve-native-c-review/SKILL.md
  autocve-rust-review/SKILL.md
  autocve-cloudflare-domains/SKILL.md
  autocve-secret-serialization/SKILL.md
```

这是建议目录，不是已实现安装器。若 AutoCVE 读取技能资源仅允许技能目录内路径，应在每个适配包内保留所需、已审查的参考副本及许可证，不扩大任意文件读取范围来解决链接问题。

每个适配包记录 `upstream_repo`、`upstream_commit`、`license`、`source_paths`、`local_changes`、`required_tools`、`applicable_scenarios`、`stages`、`output_contract_version`。`skills_sources_manifest.json` 提供本次来源清单，不是 AutoCVE 已支持的配置 schema。

在 skills 管理页面导入或同步前，应做：目录/相对链接完整性检查、宿主工具映射检查、脚本和 hooks 审查、只读权限检查、结果字段检查。先用小型无敏感数据的固定源码样例检查路由和契约，不需要做研究型 benchmark，也不需要运行被审计应用。

## 10. 首批实施顺序

**先接通方法与反馈：** audit-context-building、variant-analysis、SARIF 解释，保留现有主审计方法。先确保候选与证据记录可保存，避免多个技能竞争输出契约。

**再补非 Web：** Cloudflare 的 RPC/队列、云部署、数据生命周期，配合 sharp-edges 与 insecure-defaults，覆盖库、CLI 和后台服务。

**最后按实际语言补深度：** C/C++ 选 c-review，Rust 选 rust-review，Django 选 django-access-review，Python/JS 凭据对象选 secret-serialization。并非每个项目都要加载以上全部内容。

完整 fp-check、fuzzing、sanitizers、运行时侧信道测量暂缓。CodeQL、规则生成和高级原生分析按实际可用后端逐项接入。

## 11. 没列为核心来源的项目

- **openai/skills**：检索时 README 已明确标记 deprecated，并指向新的 OpenAI Plugins 示例来源。旧 skills 可参考，但不满足“近期维护的核心来源”的优先条件，不能仅凭高 Stars 推荐整包引入。[O1]
- **3stoneBrother/code-audit**：目录风格和内容与现有 AutoCVE 主审计知识存在明显重叠；未进行逐文件差异比对，因此不声称完全一致，也不把重复导入当能力提升。[X1]
- **mindfortai/security-skills**：主题有价值，但检索页面自述仍在建设且关注度较低，列为观察来源而非“很多人在用”的主推荐。[X2]

## 12. 来源与核对边界

本文是选型与适配建议，不是对全部上游技能质量的背书。目录中“已阅读正文”表示审读对应入口或指定前段，不表示其全部 references/scripts 都已审读。技能覆盖某类主题不等于当前 AutoCVE 已完成语言解析、调用关系、运行时兼容性和平台支持。

[A1]: https://github.com/larlarua/AutoCVE/tree/main/skill_library
[A2]: https://github.com/larlarua/AutoCVE/blob/main/skill_library/code-audit-finding/SKILL.md
[A3]: https://github.com/larlarua/AutoCVE/blob/main/skill_library/code-security/SKILL.md
[A4]: https://github.com/larlarua/AutoCVE/blob/main/skill_library/secknowledge-skill/SKILL.md
[T1]: https://github.com/trailofbits/skills/blob/1f68e03536f7980d4c0e6869596f708043a19443/README.md
[T2]: https://github.com/trailofbits/skills/blob/1f68e03536f7980d4c0e6869596f708043a19443/plugins/insecure-defaults/README.md
[C1]: https://github.com/cloudflare/security-audit-skill/blob/c1c8a8c1471069fb0e188eeaff69b8e8db6564a8/README.md
[S1]: https://github.com/getsentry/skills/blob/f57ada2d0b640406ea7e25b11d636c530e77c58b/README.md
[S2]: https://github.com/getsentry/skills/blob/f57ada2d0b640406ea7e25b11d636c530e77c58b/skills/security-review/SKILL.md
[S3]: https://github.com/getsentry/skills/blob/f57ada2d0b640406ea7e25b11d636c530e77c58b/skills/django-access-review/SKILL.md
[S4]: https://github.com/getsentry/skills/blob/f57ada2d0b640406ea7e25b11d636c530e77c58b/skills/secret-serialization/SKILL.md
[O1]: https://github.com/openai/skills
[X1]: https://github.com/3stoneBrother/code-audit
[X2]: https://github.com/mindfortai/security-skills
