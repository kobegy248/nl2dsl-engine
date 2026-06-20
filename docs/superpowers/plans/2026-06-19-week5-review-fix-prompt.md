# Claude 修复提示词：第五周代码审阅问题整改

将下面整段内容交给 Claude：

---

你现在负责修复 NL2DSL 项目第五周“评测、反馈与可观测闭环”代码审阅中发现的问题。

项目目录：

```text
D:\demo\db-gpt\NL2DSL
```

## 开始前必须阅读

按顺序阅读：

1. `AGENTS.md`
2. `CLAUDE.md`
3. `docs/specs/2026-06-19-week5-quality-feedback-observability-design.md`
4. `docs/superpowers/plans/2026-06-19-week5-quality-feedback-observability-plan.md`
5. `docs/reports/2026-06-19-week5-review-checklist.md`
6. `docs/evaluation/framework-guide.md`
7. `docs/feedback/feedback-loop-design.md`
8. `docs/audit/audit-log-design.md`
9. `docs/api/21-api-contract.md`

先检查当前工作区和已有未提交修改。不要回退、覆盖或丢失现有改动。探索代码、符号和调用关系时优先使用 Codegraph。

## 总体要求

这是一次定向修复，不要重写整个第五周实现，不要做无关重构。

必须修复下面全部 P0 和 P1 问题，并为每个问题补充能够在修复前失败、修复后通过的回归测试。

禁止：

- 通过删除、跳过、弱化测试解决问题。
- 修改断言去适配错误行为。
- 绕过 DSL、Audit、权限或租户校验。
- 把生产代码依赖放到 `tests/` 包中。
- 只修改文档而不修复实际代码。
- 只修复 `api_factory.py`，却遗漏正式生产入口。
- 自行 commit 或 push；完成后等待代码审阅。

## P0：必须优先修复

### 1. tenant_id 为空可绕过租户隔离

当前问题：

- `nl2dsl/api_factory.py` 的 `FeedbackRequest.tenant_id` 默认值为空字符串。
- `nl2dsl/feedback/store.py` 仅在请求和审计双方 tenant_id 都非空时比较。
- 调用方可以提交空 tenant_id，绕过跨租户校验。

修复要求：

1. Feedback API 的 `tenant_id` 必填且不得为空白。
2. FeedbackStore 必须执行严格相等校验。
3. 审计记录有 tenant_id 时，请求 tenant_id 缺失、为空或不一致都必须拒绝。
4. 不要只依赖 Pydantic；Store 层也必须保留防御性校验。
5. 返回项目统一的校验错误，不暴露其他租户的审计内容。

必须新增测试：

- tenant_id 缺失返回 422。
- tenant_id 为空或全空格返回 422。
- tenant_id 与审计记录不一致时拒绝。
- tenant_id 正确时提交成功。
- 直接调用 FeedbackStore 传空 tenant_id 时仍然拒绝。

### 2. 正式生产入口未接入第五周能力

项目 Quick Start 使用：

```bash
uvicorn nl2dsl.api:app
```

但 `nl2dsl/api.py` 仍使用旧 QueryResponse、旧 FeedbackRequest 和 JSONL FeedbackCollector，导致生产入口与 `create_app()` 行为不一致。

修复要求：

1. 消除 `nl2dsl/api.py` 与 `nl2dsl/api_factory.py` 的重复实现和行为漂移。
2. 推荐让 `nl2dsl/api.py` 成为薄入口，通过统一的 `create_app()` 创建正式 app。
3. 不要维护两套 API 路由、请求模型和反馈逻辑。
4. 保证 `uvicorn nl2dsl.api:app` 和测试创建的 app 使用同一实现。
5. 正式入口默认使用数据库 FeedbackStore，并与 AuditLogger 共用数据库 Engine。
6. 保持现有公开导入兼容；如确实无法兼容，应在文档中明确说明。

必须新增测试：

- 导入 `nl2dsl.api:app` 后，查询响应模型包含 query_id。
- 正式入口的 FeedbackRequest 包含 tenant_id、is_correct、issue_type。
- 正式入口提交反馈会校验 Audit、user_id 和 tenant_id。
- 正式入口不会静默退回未经校验的 JSONL 路径。

## P1：全部修复

### 3. `/api/v1/query/execute` 返回 query_id 但不写审计

当前问题：

`query_execute()` 生成并返回 query_id，但没有调用 AuditLogger。该 query_id 无法查询审计详情，也不能提交正式反馈。

修复要求：

1. `/api/v1/query/execute` 的成功、失败和澄清结果均按现有审计契约记录。
2. 审计记录必须使用响应中的同一个 query_id。
3. 至少记录 user_id、tenant_id、状态、DSL、SQL、耗时、Trace 和错误信息。
4. 检查 `/api/v1/query/dsl`、普通查询、复杂查询、SSE 最终结果是否具有同样的一致性。
5. SSE 最终事件必须返回 query_id；不能只发送空的 done 事件。

必须新增测试：

- execute 成功后可通过 audit detail API 查询同一 query_id。
- execute 返回的 query_id 可用于提交反馈。
- execute 失败也有对应审计记录。
- SSE 最终 result 事件包含 query_id，且该 query_id 可查询审计记录。

### 4. 评测矩阵结果按 case_id 相互覆盖

当前问题：

`V2Reporter.build_matrix_report()` 使用 case_id 作为唯一键。相同用例在 rule/llm、optimizer on/off 的结果会相互覆盖，Baseline 和 regression gate 可能比较错误组合。

修复要求：

1. 矩阵结果必须使用稳定的组合身份，例如：

```text
domain + case_id + generator + optimizer
```

2. 推荐报告采用嵌套结构或稳定复合键，确保四种矩阵组合都能同时保存。
3. Baseline 必须按相同矩阵组合进行比较，禁止跨 generator 或 optimizer 模式比较。
4. Markdown 和 JSON 报告必须能清楚展示每个组合。
5. 保持输出稳定排序，确保相同输入生成相同文件。

必须新增测试：

- 同一 case 的 rule/off、rule/on、llm/off、llm/on 四条结果全部保留。
- 某一个组合回退时，门禁准确报告该组合。
- 其他组合不能覆盖或掩盖该回退。

### 5. Baseline 数据集身份和兼容性校验不完整

当前问题：

- dataset hash 只包含 case id 和 query。
- 修改 expected、domain 或 tags 不会改变 hash。
- 当前结果缺少 Baseline 用例时会被静默跳过。
- 加载 Baseline 后没有严格校验数据集和矩阵兼容性。

修复要求：

1. 使用规范化后的完整评测用例计算 hash，至少包括：
   - id
   - domain
   - query
   - expected
   - tags
   - category/difficulty 等会影响评测语义的字段
2. 规范化序列化必须稳定排序。
3. Baseline 比较前校验 schema version、dataset hash 和 matrix。
4. 不兼容时默认门禁失败，并给出明确原因；不得静默继续。
5. Baseline 中存在、当前评测缺失的 case/matrix 组合必须视为回退。
6. 可增加显式 CLI 参数允许用户重新建立 Baseline，但不能默认忽略。

必须新增测试：

- 修改 expected 会改变 hash。
- 修改 domain 或 tags 会改变 hash。
- 字典键顺序变化不会改变 hash。
- 当前缺少 Baseline 用例时门禁失败。
- matrix 不一致时门禁失败并给出明确原因。

### 6. 多领域评测只是标签，没有切换真实领域环境

当前问题：

- Dataset Loader 把结构目录名 `v2` 当成业务 domain。
- EvaluationExecutor 请求 `/api/v1/query` 时不传 domain。
- QueryRequest 没有 domain。
- 复杂查询路径硬编码 `ecommerce`。
- 一个 ExecutorConfig 复用于所有领域。

修复要求：

1. 明确区分数据集版本目录和业务 domain。
2. 每个用例必须解析为真实业务 domain，例如 ecommerce、bank、supply_chain。
3. 每个 domain 必须使用对应的 DomainContext、语义配置、权限配置和执行环境。
4. 不允许仅给结果加 domain 标签，却仍使用 ecommerce 执行。
5. 设计一个清晰的 domain 路由方式：
   - API 请求显式携带 domain，或
   - EvaluationExecutor 根据 case.domain 选择对应 app/executor。
6. 删除查询链路中的 ecommerce 硬编码。
7. 未知 domain 必须明确失败，不得静默回退到 ecommerce。

必须新增测试：

- ecommerce、bank、supply_chain 用例分别进入对应 DomainContext。
- 目录名 `v2` 不会成为业务 domain。
- 未知 domain 返回明确错误。
- 相同自然语言在不同 domain 下不会共享错误的语义注册表。

### 7. Trace 完整率对 other 路径永远判定为完整

当前问题：

`_classify_path()` 无法识别的路径归类为 other，`_path_complete()` 对 other 直接返回 True。残缺 Agent Trace 和异常 Trace 会导致完整率虚高。

修复要求：

1. 定义并文档化以下路径的最小节点集合：
   - 普通成功路径
   - Optimizer 成功路径
   - Clarification 路径
   - Agent/复杂查询路径
   - Error/failed 路径
2. 无法识别的路径不得默认算完整。
3. unknown/other 应单独统计，默认计为不完整。
4. Trace 为空必须计为不完整。
5. 报告中增加各路径总数、完整数和完整率，便于定位问题。

必须新增测试：

- 只有一个 agent 节点的 Trace 不完整。
- 完整 Agent 路径判定正确。
- 空 Trace 不完整。
- 未知路径不完整。
- 现有成功、Optimizer、Clarification 路径行为不回退。

### 8. 正式 CLI 依赖 tests 包

当前问题：

- `nl2dsl/evaluation/v2_cli.py`
- `nl2dsl/feedback/exporter.py`

从 `tests.e2e.mock_data` 导入生产运行依赖。安装 wheel 后通常没有 tests 包，CLI 会失败。

修复要求：

1. `nl2dsl` 包内的任何正式 CLI 不得导入 `tests.*`。
2. 将必要的 demo/mock 数据能力移动到正式包中的明确模块，或让 CLI 通过正式配置和数据库 URL 启动。
3. Feedback Exporter 默认行为必须明确：
   - 指向用户提供的真实数据库；或
   - 明确要求 `--db-url`。
4. 不得默认创建一个空的内存数据库并报告“成功导出 0 条”，造成误导。
5. CLI `--help` 不应触发数据库、模型或测试夹具初始化。
6. 增加 wheel/隔离环境导入测试，至少验证不含 tests 包时 CLI 模块仍可导入。

必须新增测试：

- 搜索正式包不存在 `from tests` 或 `import tests`。
- 三个 console script 的 `--help` 都能成功执行。
- Feedback Exporter 未提供必要数据库参数时明确报错。
- CLI 模块在模拟“tests 包不可用”的环境中仍能导入。

## 同步修复的相关问题

在不扩大范围的前提下，同时处理：

1. `FeedbackStore.submit()` 的并发去重竞争：
   - 不要使用不具原子性的“先 SELECT、后 INSERT”作为最终保障。
   - 捕获唯一约束竞争，返回已有 feedback_id，而不是抛出 500。
2. Candidate Exporter：
   - candidate_id 必须根据稳定候选身份生成，至少包含 query 和 corrected_dsl，避免同问题不同修正产生重复 ID。
   - 不要把 `DSL.data_source` 直接当作业务 domain。
   - 输出必须稳定排序。
3. 管理 API：
   - Feedback 和 Audit 管理查询必须具有明确租户范围。
   - 不得在未限定 tenant 的普通调用中返回所有租户反馈。
   - 如果项目尚无认证框架，至少实现强制 tenant 过滤并在文档中记录剩余认证风险。
4. 修正本次修改中出现的乱码注释和中文文档编码问题，统一使用 UTF-8。

## 测试与验证

先修复本地测试环境。当前 `.venv\pyvenv.cfg` 可能仍指向不存在的：

```text
C:\Users\gaoyu\AppData\Local\Programs\Python\Python310
```

不要修改项目代码来绕过环境问题。必要时使用当前可用 Python 重新创建 `.venv`，然后按照 `pyproject.toml` 安装开发依赖。

完成后至少执行：

```bash
python -m pytest tests/unit/ -q
python -m pytest tests/evaluation/v2/ -q
python -m pytest tests/integration/ -q
python -m pytest tests/e2e/test_feedback_audit_api.py tests/e2e/test_api.py -q
python -m nl2dsl.evaluation.v2_cli --help
python -m nl2dsl.quality.cli --help
python -m nl2dsl.feedback.exporter --help
git diff --check
```

还必须执行：

1. 通过正式入口 `nl2dsl.api:app` 跑反馈与审计链路测试。
2. 跑一次真实 rule 模式矩阵评测，确认 JSON 和 Markdown 报告包含所有 case/matrix 组合。
3. 建立 Baseline 后故意降低一个组合的分数，确认 regression gate 非零退出。
4. 修改一个用例的 expected，确认 dataset hash 改变且旧 Baseline 被拒绝。
5. 检查正式包不存在对 `tests.*` 的运行时依赖。

如果完整测试耗时过长，可以分组运行，但最终必须提供每组准确的通过、失败和跳过数量。不得只写“测试通过”。

## 文档更新

根据实际最终行为同步更新：

- `docs/api/21-api-contract.md`
- `docs/audit/audit-log-design.md`
- `docs/evaluation/framework-guide.md`
- `docs/evaluation/optimizer-guide.md`
- `docs/feedback/feedback-loop-design.md`
- `docs/specs/2026-06-05-next-stage-roadmap.md`

文档正文使用中文，代码标识、命令和 API 字段保持英文。

重点写清：

- 正式 app 的唯一创建方式。
- Feedback tenant_id 的强校验。
- Query ID 与 Audit 的完整关联。
- 多领域评测如何选择真实 DomainContext。
- Baseline 数据集与矩阵兼容规则。
- Trace 各路径完整性定义。
- Feedback Exporter 的数据库参数与租户边界。

## 完成后的回复格式

完成后请提供：

1. 按 P0/P1 对照的修复摘要。
2. 修改文件列表。
3. 每个问题对应的回归测试位置。
4. 执行过的完整测试命令及准确结果。
5. 真实矩阵评测和 regression gate 验证结果。
6. 尚未解决的问题或风险。
7. 明确说明没有自行 commit 或 push。

完成开发后停止，等待代码审阅。

---
