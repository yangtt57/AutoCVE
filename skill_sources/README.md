# 固定上游来源

这里保存 Trail of Bits、Cloudflare、Sentry 三个固定提交的完整原始归档与原始许可。提交、下载地址和 SHA-256 见根目录 `skills_sources_manifest.json`。归档只作离线追溯，不在应用启动或审计时解压、导入、运行脚本或发现测试。

运行时只读取 `skill_library/autocve-*` 中经清单锁定的 Markdown 适配内容。原件中的子代理、命令、hooks、模型选择、动态验证和报告步骤不是 AutoCVE 的可用能力。许可证和第三方归属说明见各适配包的 `NOTICE.md`；Trail of Bits 派生文本沿用 CC BY-SA 4.0，Django 参考保留 OWASP 的 CC BY-SA 4.0 说明。

在项目根目录执行 `python3 scripts/manage_audit_skills.py verify` 可校验归档、许可、来源路径、相对链接、元数据及实际加载资源哈希。`fetch` 只补回缺少且匹配固定哈希的归档，不更新提交或执行上游代码。
