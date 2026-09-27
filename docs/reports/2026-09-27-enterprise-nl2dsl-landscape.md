# 企业级自然语言语义查询能力调研与 NL2DSL 对标

> 调研日期：2026-09-27。
> 项目快照：`main`，提交 `503204c`；开始调研时工作区干净。
> 方法：查阅厂商官方文档和官方开源仓库，并静态核对本项目文档、代码及历史报告。本次未运行产品横评、项目测试或真实 LLM 评测，不据此宣称性能或准确率领先。

## 1. 结论

NL2DSL 的技术方向与当前企业级语义问数路线一致：让模型识别业务含义，由受控的语义定义、编译器和权限系统决定如何查询。但 **DSL First 本身已经不是独有优势**，下一阶段需要证明的价值是：中文业务口径可靠、部署可控、权限不可绕过、答案可追溯，以及接入一个真实业务域的成本足够低。

按当前代码证据，项目可定位为“具备完整查询链路和质量工具的工程原型，适合继续建设受控试点”。尚不足以仅凭测试数量、SQL 方言支持或已有权限过滤，就宣称达到企业生产级。

建议主线：**面向企业内部应用和 AI Agent 的可治理语义查询服务**。Web 问数页作为验证入口，REST 与后续 MCP 作为集成入口，共用同一套 DSL、身份权限、编译和审计逻辑。

这不是把六月路线从头再做一遍：复杂过滤、时间、隐式 JOIN、TopN、占比、反馈评测，以及七月统计信息治理均已有实现，应直接复用。

## 2. 业界在做什么

“NL2DSL”并不是这些厂商统一使用的产品名称。相关产品通常归为 Conversational Analytics、Semantic Layer 或 Data Agent；其内部可能生成受控查询参数、语义查询、SQL、DAX 或 KQL，不能将它们都等同于本项目的 DSL 架构。

| 产品 / 路线 | 本次核实到的公开能力 | 对本项目的启示 |
|---|---|---|
| Looker Conversational Analytics | 从 LookML 选择字段、过滤、排序和 LIMIT，由 Looker 组合并执行查询；支持业务值检索、澄清和 verified queries。[官方概览](https://docs.cloud.google.com/looker/docs/conversational-analytics-overview) | 与本项目“模型理解、系统编译”最接近的参照；需要继续做好值解析、受控 Join 和指标一致性 |
| Snowflake Cortex Analyst / Cortex Agents | Analyst 使用语义资产生成 SQL；当前 Analyst 文档建议迁移至 Cortex Agents。Agents 将结构化查询、检索等工具接入编排，并提供运行监控。[Analyst](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst)、[Agents](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents) | 单次问数之外，开始比较工具权限、运行预算、可观测性和复杂任务完成质量 |
| Databricks Genie Agents | 当前文档说明原 Genie Spaces 已更名为 Genie Agents；配置受信数据、样例和业务规则，按最终用户的 Unity Catalog 权限访问数据。[设置与权限](https://docs.databricks.com/aws/en/genie-agents/set-up) | “填写 tenant_id”不等于身份可信；领域空间、数据授权和用户身份需要贯通 |
| Microsoft Fabric data agent | 面向不同数据源使用 SQL/DAX/KQL 工具；数据访问依托 Entra 用户身份；支持草稿和发布版本，并继承底层 RLS/CLS。[查询架构](https://learn.microsoft.com/en-us/fabric/data-science/semantic-model-best-practices)、[认证](https://learn.microsoft.com/en-us/fabric/data-science/how-to-create-data-agent)、[发布与分享](https://learn.microsoft.com/en-us/fabric/data-science/data-agent-sharing) | 语义配置需要可发布、可回退；用户能使用 Agent，并不代表能访问它连接的全部数据 |
| Cube | 语义模型提供基于用户属性的访问策略；MCP 通过 OAuth 认证，工具和部署访问范围受角色约束。[行级权限](https://docs.cube.dev/docs/data-modeling/access-control/row-level-security)、[MCP](https://docs.cube.dev/docs/integrations/mcp-server) | 对外开放的是受控分析能力；MCP 必须继承身份权限，不能成为另一条绕过治理的执行路径 |
| dbt Semantic Layer / MetricFlow | 通过 entities 和语义关系规划 Join，限制会重复计数的危险连接；MCP 提供指标、元数据、血缘等工具。[Join 语义](https://docs.getdbt.com/docs/build/join-logic)、[MCP](https://docs.getdbt.com/docs/dbt-ai/about-mcp) | 有 Join 路径还不够，还需要粒度、基数和可加性规则；生态接入可复用企业既有语义资产 |
| 腾讯音乐 SuperSonic | 官方仓库将 Chat BI 与 Headless BI 结合，提供语义建模界面、规则和 LLM 解析、多轮会话及数据集/列/行三级权限。[官方仓库](https://github.com/tencentmusic/supersonic) | 中文开源路线的重要参照；需在特定业务域的可靠性、轻量交付或可嵌入性上形成差异 |

上述是“官方明确提供什么”的核查，不是跨产品性能排名。云平台内建能力、开源框架能力和可私有部署能力也不能直接互换。

## 3. 企业级能力的共同方向与边界

### 3.1 语义资产成为核心

指标公式、维度、时间口径、合法 Join、同义词和示例答案，需要可维护并能限制生成行为。Looker 直接由语义模型承担查询组合；MetricFlow 进一步用实体类型约束危险 Join。[Looker 查询机制](https://docs.cloud.google.com/looker/docs/conversational-analytics-overview)、[MetricFlow Join](https://docs.getdbt.com/docs/build/join-logic)

由此推导：本项目下一步应把 YAML 从“能加载的配置”推进为“有版本、负责人、验证和发布流程的业务契约”。单纯扩大 Prompt 或增加规则数量不能替代这项工作。

### 3.2 身份权限贯穿查询全过程

Genie 按最终用户的数据权限执行，Fabric 继承数据源权限，Cube MCP 的入口也绑定 OAuth 身份和角色。这些机制的共同点，是授权依据来自可信身份系统。[Genie 权限](https://docs.databricks.com/aws/en/genie-agents/set-up)、[Fabric 权限](https://learn.microsoft.com/en-us/fabric/data-science/data-agent-sharing)、[Cube MCP 权限](https://docs.cube.dev/docs/integrations/mcp-server)

由此推导：项目必须同时保护查询、元数据发现、RAG、审计、反馈、审核恢复和后续缓存，不能只保护最终 SQL 的 WHERE 条件。

### 3.3 质量从“生成成功”升级为“答案正确”

Snowflake Analyst 评测会执行生成 SQL，与已验证查询的结果比较；被选作评测的 verified queries 会从本次生成上下文中移除。Genie 的 Chat benchmark 对比 SQL 或结果集，Agent benchmark 则使用评审模型，二者不能混作同一准确率。[Snowflake 评测](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst-evaluations)、[Genie 评测](https://docs.databricks.com/aws/en/genie-agents/monitor)

由此推导：本项目应分别统计 DSL 语义匹配、结果正确率、恰当澄清/拒绝和端到端完成率；真实测试集不能又作为 RAG 的答案示例直接喂给生成器。

### 3.4 多轮分析和运行管理逐渐产品化

Looker 的会话 API 要求维护消息历史，否则追问不能继承上下文。Snowflake Agents 提供线程、工具调用、反馈和延迟监控，并区分线上观测与离线评测。[Looker 会话 API](https://docs.cloud.google.com/looker/docs/best-practices/ca-apis-in-looker-api-best-practices)、[Snowflake 观测](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-monitor)

多轮不只是把聊天记录拼进 Prompt。需要维护明确的语义状态，并在每轮重新授权、校验和编译。

### 3.5 能力仍有明确边界

例如，Looker 文档对预测、高级统计、可视化和返回规模均列出限制；Genie Agent 只查询显式配置的数据源，仍需业务人员维护上下文。[Looker 限制](https://docs.cloud.google.com/looker/docs/conversational-analytics-overview)、[Genie 数据范围](https://docs.databricks.com/aws/en/genie-agents/set-up)

因此不建议把“任意问题都能答”作为本项目目标，也没有本次可核实的统一行业准确率可以直接用来宣布领先或落后。应定义支持范围、保留集、数据快照、权限上下文及计分方式后再比较。

## 4. 项目能力对照

下表中的“已有”表示发现对应实现，不代表已经通过本次运行验收。源码位置均基于 `503204c`。

| 能力 | 当前证据 | 判断 / 下一步 |
|---|---|---|
| NL → DSL → SQL 受控执行 | `nl2dsl/dsl/models.py`、`graph/builder.py`、`sql_engine/builder.py` | 核心路线完整，应继续作为唯一执行契约 |
| 中文过滤、时间、值映射 | `dsl/generator.py`、`query/time_resolver.py`、`semantic/resolver.py` | 有实现；需要独立保留集证明真实业务覆盖率 |
| 复杂分析 | `agent/orchestrator.py`、`query/post_processor.py` | 有拆解、TopN、占比；尚需粒度正确性与大结果规模验证 |
| 语义配置 | `semantic/registry.py:11` 读取 YAML 到字典 | 未见完整的语义版本发布、认证、回滚和请求快照机制 |
| 治理权限 | `permission/row_level.py:8`、`api_factory.py:263` | 有注入和租户过滤；缺可信身份，未知用户的行级策略还会直接返回原 DSL |
| 评测矩阵与回归 | `evaluation/execution.py`、`v2_runner.py`、`baseline.py:132` | 已有真实链路、rule/llm × on/off、数据集 hash；需要强化结果正确性门槛与发布集成 |
| 反馈资产 | `feedback/store.py`、`feedback/exporter.py:58` | 有持久化、去重及候选导出；审核、发布和验证效果仍需产品闭环 |
| 审计与诊断 | `audit/logger.py`、`quality/analyzer.py` | 有查询关联和质量报告；应补语义/权限版本、模型版本、成本及保留策略 |
| 多轮与澄清 | `api_factory.py:263`、`engine.py:73`、`QueryPage.tsx:39` | 有澄清节点、内存检查点和人工恢复接口；没有完整的持久多轮业务闭环 |
| 前端可用性 | `web/src/pages/QueryPage.tsx:32`、`:123` | 同步问数、图表已在；进度为固定状态列表，查询结果页传入空 Trace，澄清被转为错误 |
| SQL 调优与风险预检 | `builder.py:219`、`query/sandbox.py:85` | 有统计驱动编译和 SQLite EXPLAIN 启发式；先确保语义不变，再证明性能收益 |
| 生产执行保障 | `sql_engine/executor.py:8`、`config.py:25` | 执行器同步读取全部结果；未见配置的 query_timeout 在执行层落实为数据库强制超时 |
| 多实例与交付 | `engine.py:73`、`:157`、`docs/architecture/04-deployment.md` | 检查点为内存，Embedding 有本机绝对路径；多实例、迁移和干净环境启动需补验收 |
| Agent 生态 | 检索 `nl2dsl`、`web/src` 未见 MCP 服务实现 | 可在身份和核心执行闭环完成后，加薄适配层 |

现有多域自治不能直接推导为跨数据库联邦查询；SQL 方言转换也不能直接推导为对应数据库的权限、超时、审计和 EXPLAIN 已完整支持。

## 5. 最值得优先解决的具体问题

### 5.1 可信身份与默认拒绝

`QueryRequest` 接受请求方提供的 `user_id` 和 `tenant_id`；路由未见统一的认证依赖。`RowLevelSecurity.inject()` 对未配置用户直接返回 DSL。API 文档也明确说明当前尚无认证框架。

因此，对于能直接访问当前 API 的调用方，租户参数不是可靠的授权边界。建议先接可信身份上下文，在服务端解析用户、租户、角色、允许访问的业务域；未知身份默认拒绝。元数据与审核恢复接口必须一起纳入。若部署环境另有认证网关，本次未检查其配置，仍需验证身份不能被下游参数替换。

### 5.2 物理优化不能改变查询含义

`nl2dsl/sql_engine/builder.py:219` 在 `indexed=true` 且 `selectivity=high` 时，将同一个 `like` 值编译成 `value%`，其他情况则是 `%value%`。

静态反例：查询“商品名包含手机”，`旗舰手机` 满足包含匹配，却不满足“手机开头”。只增加索引元数据，就可能改变答案。

建议显式区分 contains / starts_with / ends_with / pattern 等受控语义；物理统计只影响执行选择，不改变匹配集合。F006 的枚举 `like → in` 也应要求明确的业务值解析证据，而不能仅凭存在 `value_map` 就推断模糊匹配等同精确匹配。

这是源码与查询语义可以直接说明的风险，本次未进行运行复现。后续应先补结果级反例测试，再修实现与相关设计文档。不能用“SQL 更快”抵消“结果漏行”。

### 5.3 评测分数不能冒充业务正确率

当前 V2 的 `run_single()` 主要评分 intent、metric、filter、planner、governance；`score_observation()` 收到执行观测后仍主要按最终 DSL 打分。虽然 Observation 已收集结果数据，尚未把独立标准答案的结果集对比作为这条主评分路径的硬门槛。

另外，无期望治理项时治理维度会记为 N/A 的 1.0，不能据此宣称越权用例全部通过。明确应返回澄清的测试，也需要独立计分规则，不能统一视为失败。

建议同时保留两类评价：语义分用于诊断，结果与安全断言用于验收。后者由独立人工核对的答案、固定数据快照和已授权数据范围定义，不能依赖被测编译器同时生成实际和期望结果。

### 5.4 历史基线需要重建

仓库中的 `reports/baselines/rule-optimizer-off.json` 标记生成时间为 2026-06-19、提交为 `7191fe3`，早于本次快照。历史记录中：

- 加权分数约 81.6%，但通过用例是 9/22，约 40.9%。两者不是同一个指标。
- `reports/v2_rule_matrix/benchmark_report.json` 的 on/off 历史分数相同，不能证明目前优化器没有收益，也不能证明已有收益。
- 历史报告中出现 0ms 的 P95，不可用作真实端到端性能承诺。

这些数字只说明“必须重新建立可复现的当前基线”，不能用来断言九月版本或真实 LLM 的准确率。本次没有重跑评测。

### 5.5 从图节点走到业务闭环

当前查询页将 clarification 当作错误；请求没有 conversation_id；内存检查点不能保证服务重启后的恢复。后端已有 `/query/resume`，不能说完全没有人工审核，但它仍需可信审批人、领域路由、过期校验、持久化和完整审计。

建议下一阶段让用户真正完成：“问数 → 澄清 → 得到结果 → 追问 → 查看口径 → 反馈 → 审核进入评测”。这比新增一个孤立的意图识别分支更能验证产品价值。

## 6. 下一阶段产品取舍

| 方向 | 适配程度 | 建议 |
|---|---|---|
| 企业受控语义查询服务，供 Web、内部应用和 Agent 使用 | 与当前 DSL、治理和插件架构吻合 | 主方向；先在一个业务域完成可验证试点 |
| 完整 BI 平台，补齐拖拽建模、报表设计、权限管理和所有图表 | 工作量大，现有查询引擎优势容易被前端平台建设稀释 | 暂缓；只补问数、澄清、口径说明、反馈与审核所需界面 |
| 继续横向增加意图、模型与数据库种类 | 演示范围扩大，但不能直接解决可信身份和答案正确性 | 按试点需求增加，不作为独立主线 |

建议的差异化假设是：**中文高约束业务 + 可部署在企业环境 + 可嵌入的 DSL 契约 + 可审计的可靠答案**。这是假设，必须用真实用户任务完成率和接入成本验证；不能只凭架构图成立。

首个领域优先选择有业务专家和只读数据可供验收的领域。没有外部试点资源时，可先用 ecommerce 完成工程闭环；不建议因 bank 已有样例就直接承诺金融生产可用。

## 7. 后续行动

下一阶段的范围、六周顺序、验收指标与交付边界见 `docs/specs/2026-09-27-enterprise-pilot-roadmap.md`。

优先顺序：可信身份和语义正确性 → 可版本化语义资产与结果评测 → 可持续会话和反馈 → 可运营的试点执行环境 → 复用治理的 MCP 接入。

本次只新增调研和规划文档，不改变运行代码，不提交或推送仓库。
