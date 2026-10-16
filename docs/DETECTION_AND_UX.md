# 检测与界面改进

新建审计默认启用「源码发现与覆盖账本」，可选择快速扫描、深入分析或全面审计。关闭该选项可使用原有 CVE 挖掘与验证流程；一键 CVE 和漏洞管理中的 Pi / Docker 动态验证入口继续保留。

## 检测链路

- Semgrep 的旧版 `max_index_findings` 参数保留兼容，但不再截断入库结果。每个原始 occurrence 都有自己的 ID，先完整保存，再按优先级分批研判。
- 旧研判流程达到轮次预算时，保留已完成的发现与未处理队列，任务标为部分完成。最终结果直接从持久化队列汇总，避免模型收尾输出覆盖已有结果。
- 源码账本模式使用已有 Tree-sitter 依赖索引符号、导入及未解析调用名；Python 保留原生 AST。语法解析失败、超大文件和未支持的语言仍保留显式限制。
- 新增 Java / Kotlin（Spring、JAX-RS、Servlet、Ktor）、Go（net/http、Gin、Echo、Fiber）、C#（ASP.NET）、PHP（Laravel、Symfony）、Ruby（Rails、Sinatra）、Rust（Axum、Actix）、Swift（Vapor）的入口注册形态识别，增强 JS/TS（Express、Koa、Fastify、NestJS）；C/C++ 支持函数、CLI 和库入口导航。
- 注册形态匹配前屏蔽注释和字符串，防止把示例代码当成入口。框架匹配属于启发式导航，仍需 Agent 核查导入、注册、挂载、调用方和运行配置。
- 工作包按具体入口与组件拆分，每包最多 24 个入口、8 个文件，并轮流安排不同组件。未识别到入口的源码与配置仍会进入补充分析，不再因检测到 Docker/CI 而漏掉源码。
- 信任边界记录关联入口、调用方、保护资源与鉴权线索。提示 Agent 按「输入 → 身份 / 租户 / 对象权限 → 敏感操作」追踪，并查阅全局中间件、配置、共享服务与反证。注解名称不构成防护生效的证明。

## 覆盖与恢复

流程进度、规则扫描文件数、实际阅读文件数、检查回执和未处理工作包分别展示。实际阅读仅统计工具返回过的源码片段；任务完成不再把所有文件标成已分析，也不再根据「没有发现」生成安全满分。无可核验记录的历史任务显示「未记录」。

源码账本区分可继续的未处理工作、扫描重试、能力限制和补查轮次上限。只有确实存在可调度工作时才显示继续按钮。仅选择深入分析时，规则扫描的主动跳过不会导致任务永久显示部分完成，也不会先尝试准备扫描容器。

历史源码快照和首轮检查点继续保持不变；新增入口识别能力应通过新建审计应用。源码阅读和同名调用导航不能替代完整调用图、运行验证或人工判断。

## 界面

- 首页、导航、主要页面、按钮和表单统一使用浅色平面样式，减小圆角与阴影；保留清晰的窄屏导航和键盘操作入口。
- 创建任务提供分析预设与源码账本模式预算，支持已有本地目录项目。切换项目会清空旧文件范围，并隔离过期的分支 / ZIP 响应。
- 审计列表明确显示实际阅读信息，并在所有运行阶段保持刷新；终态发现面板停止自动轮询。
- 候选支持严重程度与文本筛选；源码证据以文件名、真实行号与代码片段展示，版本历史展示结论变化，原始 JSON 收到可展开的详情中。
- 漏洞列表保留报告和动态验证作为主要操作，编辑、CVE 提交与删除收进更多菜单；高级筛选可折叠，常用状态中文化。

报告与动态验证状态同步、CVSS 评分规则及评测体系不在本次变更范围内。

## 框架规则参考

实现参考项目已有解析器，并核对了框架官方文档中的注册方式：

- [Spring 请求映射](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-controller/ann-requestmapping.html)
- [Go net/http](https://pkg.go.dev/net/http)
- [ASP.NET Minimal APIs](https://learn.microsoft.com/en-us/aspnet/core/fundamentals/minimal-apis?view=aspnetcore-10.0)
- [Laravel 路由](https://laravel.com/docs/12.x/routing)
- [Rails 路由](https://edgeguides.rubyonrails.org/routing.html)
- [Axum Router](https://docs.rs/axum/latest/axum/struct.Router.html)
- [Actix URL dispatch](https://actix.rs/docs/url-dispatch/)
- [Ktor 路由](https://ktor.io/docs/server-routing.html)

测试包括超过 200 条告警及重复 occurrence 保留、多语言符号与入口、注释 / 字符串排除、未匹配源码补充调度、预算耗尽后结果保留、真实阅读统计和恢复条件。界面检查使用浏览器与隔离的本地示例数据，没有启动新的模型审计或 PoC 执行。
