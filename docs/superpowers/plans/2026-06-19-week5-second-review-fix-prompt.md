# Claude 修复提示词：第五周第二轮审阅整改

将下面整段内容交给 Claude：

---

你现在负责继续修复 NL2DSL 项目第五周功能在第二轮代码审阅中发现的问题。

项目目录：

```text
D:\demo\db-gpt\NL2DSL
```

## 开始前阅读

按顺序阅读：

1. `AGENTS.md`
2. `CLAUDE.md`
3. `docs/specs/2026-06-19-week5-quality-feedback-observability-design.md`
4. `docs/superpowers/plans/2026-06-19-week5-quality-feedback-observability-plan.md`
5. `docs/superpowers/plans/2026-06-19-week5-review-fix-prompt.md`
6. `docs/reports/2026-06-19-week5-review-checklist.md`
7. 当前工作区的全部未提交修改

不要回退或覆盖已有修改。先使用 Codegraph 理解相关符号和调用链，再开始修改。

## 工作方式

- 这是第二轮定向整改，不要重写第五周功能。
- 使用 TDD：先补能稳定复现问题的失败测试，再修改实现。
- 不得删除、跳过、弱化现有测试。
- 不得通过修改断言适配错误行为。
- 由你负责运行全部测试，并提供准确测试结果。
- 不要自行 commit 或 push，完成后等待 Codex 复审。

## P0：详情接口必须实施租户隔离

### 当前问题

以下按 ID 查询接口没有要求 tenant_id，也没有验证记录所属租户：

```text
GET /api/v1/admin/feedback/{feedback_id}
GET /api/v1/admin/audit/queries/{query_id}
```

知道其他租户的 feedback_id 或 query_id 即可读取数据。

### 修复要求

1. 两个详情接口必须要求非空 `tenant_id`。
2. 查询结果的 tenant_id 必须与请求 tenant_id 严格一致。
3. 不一致时不得泄露记录是否存在，统一返回 404。
4. 租户校验应尽量下沉到 Store/Logger 查询方法，避免 API 层取出跨租户数据后再过滤。
5. 列表和详情接口必须采用一致的租户边界。
6. 不要把客户端传入 tenant_id 当成管理员认证；文档中保留“仍需接入正式认证授权”的风险说明。

必须新增测试：

- 缺少 tenant_id 时拒绝。
- tenant_id 为空白时拒绝。
- 正确租户可以读取详情。
- 错误租户读取 feedback detail 返回 404。
- 错误租户读取 audit detail 返回 404。
- 响应不得包含其他租户的 SQL、DSL、Trace、问题文本或反馈内容。

## P1：query/execute 的所有失败都必须审计

### 当前问题

`/api/v1/query/execute` 目前只在图正常返回 result 后写 Audit。以下异常会跳过审计：

- `DSL(**req.dsl)` 解析异常。
- `_get_domain_graph()` 或 `graph.ainvoke()` 抛异常。
- SQL 构建、扫描或执行过程中抛异常。

### 修复要求

1. 从 query_id 创建后开始，用统一的 `try/except/finally` 或等价结构覆盖整个执行流程。
2. 成功、clarification、业务错误和未预期异常都必须写 Audit。
3. 同一个请求只能形成一条 query_id 对应的最终审计记录；可使用现有 UPSERT 更新。
4. 对未预期异常记录安全的错误类型和信息，不要泄露密钥或连接串。
5. 保持统一异常处理与正确 HTTP 状态码。

必须新增测试：

- DSL Schema 校验失败后存在 error Audit。
- graph 抛出异常后存在 error Audit。
- SQL 执行异常后存在 error Audit。
- 成功请求仍只对应同一个 query_id。

如果请求在响应前失败，需设计可验证的 query_id 关联方式。推荐在错误响应体中返回 query_id，并同步更新 API 契约。

## P1：修复简单 SSE 的最终状态和异常审计

### 当前问题

`stream_mode="updates"` 返回的是节点更新块，不是完整 QueryState。当前代码把最后一个 chunk 当作完整状态，可能将真实失败记录为空内容的 success。

简单 SSE 的 `graph.astream()` 抛异常时，也没有 error 事件和 error Audit。

### 修复要求

1. 不得把最后一个 update chunk 当作完整状态。
2. 流结束后通过 LangGraph 正式状态 API 获取最终状态，或在消费更新时正确合并状态。
3. 最终 `result` 事件至少包含：
   - query_id
   - status
   - dsl
   - sql
   - data 或结果摘要
   - error（失败时）
4. `done` 事件保留 query_id。
5. SSE 成功、clarification 和失败均写入准确 Audit。
6. `astream()` 抛异常时输出结构化 `error` 事件，写 error Audit，随后正常结束流。
7. 不得把异常吞掉后伪装为 success。

必须新增测试：

- 最后一个 update chunk 不是完整状态时，result 仍包含真实最终状态。
- 简单 SSE 成功审计包含 DSL、SQL 和 Trace。
- 简单 SSE 图返回 error 时审计状态为 error。
- `astream()` 抛异常时客户端收到 error 事件，Audit 中存在同 query_id 的 error 记录。
- result/done 中 query_id 与 Audit 一致。

## P1：Agent Trace 生产与完整率规则必须一致

### 当前问题

质量分析器要求 Agent Trace 至少包含：

```text
agent + 一条子查询执行证据
```

但普通复杂查询和复杂 SSE 的 Audit 目前只写：

```json
{"step": "agent"}
```

因此所有复杂查询会固定被判为 Trace 不完整。

### 修复要求

1. 不要降低完整率规则来掩盖生产 Trace 缺失。
2. 从 AgentOrchestrator 的真实执行结果、子查询结果或事件中收集 Trace。
3. 复杂查询 Trace 至少体现：
   - agent/orchestration
   - plan 或 decomposition
   - 每个 subquery 的开始和结束
   - 子查询执行状态
   - aggregation/explanation
4. 统一普通复杂查询与复杂 SSE 的 Trace 格式。
5. 质量分析器应识别实际生产的步骤名称，不要维护一套永远不会生成的名称。

必须新增测试：

- 仅有 agent 节点仍判为不完整。
- 正常复杂查询产生满足规则的完整 Trace。
- 某个子查询失败时 Trace 能体现失败，不能伪装完整成功。
- 普通复杂查询和复杂 SSE 的 Trace 核心步骤一致。

## P1：Baseline 身份校验必须 fail-closed

### 当前问题

Baseline 只有在双方均提供以下字段时才比较：

- schema_version
- dataset_hash
- matrix_combos

删除这些字段的旧或损坏 Baseline 可以绕过兼容性检查。

### 修复要求

1. Baseline 和当前报告必须包含所有必需身份字段。
2. 任一必需字段缺失、为空或格式错误时，回归门禁失败。
3. `matrix_combos=[]` 与字段缺失要区分处理。
4. schema_version 不受支持时明确失败。
5. 错误信息说明是“Baseline 不兼容或损坏”，不要默认为零分继续比较。
6. 可提供显式迁移或重新建立 Baseline 的操作说明，但不得自动放行。

必须新增测试：

- Baseline 缺失 schema_version 时失败。
- Baseline 缺失 dataset_hash 时失败。
- Baseline 缺失 matrix_combos 时失败。
- 当前报告缺失对应字段时失败。
- 不支持的 schema_version 失败。
- 完整且一致的身份字段能够正常进入分数比较。

## P1：默认 V2 CLI 必须真正支持多领域

### 当前问题

`ApiEvaluationExecutor` 已支持 `domains` 映射，但 `build_default_executor_config()` 仍只构造 ecommerce 单领域配置。

新增的 bank 和 supply_chain 样例配置没有进入默认 CLI 执行环境。

### 修复要求

1. 默认 CLI 构造真实的多领域 `ExecutorConfig.domains`：
   - ecommerce
   - bank
   - supply_chain
2. 每个领域独立配置：
   - Engine/样例数据库
   - registry_dict
   - permissions
   - sensitive_columns
   - masking_rules
   - eval user/tenant
3. 每个 case 按 case.domain 进入对应配置。
4. `--domain` 过滤后只初始化或运行需要的领域也可以，但行为必须明确。
5. 未知领域必须明确失败。
6. 默认数据集中的领域声明必须与这些配置一致。

必须新增测试：

- 默认 ExecutorConfig 同时包含三个领域。
- ecommerce 用例使用 ecommerce registry。
- bank 用例使用 bank registry。
- supply_chain 用例使用 supply-chain registry。
- 同一个指标名称在不同领域不会串用定义。
- CLI 分别使用 `--domain ecommerce/bank/supply_chain` 能完成 rule 模式评测。

## P2：清理与一致性

1. 修复本轮新增或修改文件中的乱码中文注释与文档内容，统一 UTF-8。
2. 修复 `git diff --check` 报告的多余空行。
3. 检查正式包中不存在 `from tests` 或 `import tests`。
4. 测试代码可以引用 tests 内 fixture，但正式运行代码不得依赖 tests 包。
5. 不要顺带扩大 SQLBuilder、Prompt 或业务语义改动；若这些改动不是本轮问题所必需，请解释保留原因和测试依据。

## 测试责任

你的环境可以正常运行项目 `.venv`，请使用：

```powershell
.\.venv\Scripts\python.exe
```

先确认：

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pytest --version
```

然后至少运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/ -q
.\.venv\Scripts\python.exe -m pytest tests/evaluation/v2/ -q
.\.venv\Scripts\python.exe -m pytest tests/integration/ -q
.\.venv\Scripts\python.exe -m pytest tests/e2e/test_feedback_audit_api.py tests/e2e/test_api.py tests/e2e/test_audit_query_api.py -q
.\.venv\Scripts\python.exe -m nl2dsl.evaluation.v2_cli --help
.\.venv\Scripts\python.exe -m nl2dsl.quality.cli --help
.\.venv\Scripts\python.exe -m nl2dsl.feedback.exporter --help
git diff --check
```

还必须执行以下行为验证：

1. 使用错误 tenant_id 读取 feedback/audit detail，确认返回 404。
2. 构造 execute DSL 解析异常，确认 error Audit 存在。
3. 模拟简单 SSE 的 `astream()` 抛异常，确认 error 事件与 Audit。
4. 跑一条真实复杂查询，确认 Agent Trace 被质量分析器判为完整。
5. 删除 Baseline 的 dataset_hash，确认 regression gate 非零退出。
6. 分别运行 ecommerce、bank、supply_chain 的 rule 模式评测。

不得只运行新增测试。必须提供每条命令的准确通过、失败、跳过数量和退出码。

## 文档同步

按实际最终行为更新：

- `docs/api/21-api-contract.md`
- `docs/audit/audit-log-design.md`
- `docs/evaluation/framework-guide.md`
- `docs/feedback/feedback-loop-design.md`
- `docs/specs/2026-06-05-next-stage-roadmap.md`

重点写清：

- 详情接口 tenant_id 契约。
- 错误响应中的 query_id。
- SSE result/error/done 事件格式。
- Agent Trace 最小完整路径。
- Baseline 必需身份字段。
- 默认 CLI 的三个业务领域环境。

正文使用中文，代码标识、命令和 API 字段保留英文。

## 完成后回复格式

完成后请提供：

1. 按 P0/P1/P2 对照的修复摘要。
2. 修改文件列表。
3. 每个问题对应的测试文件和测试名称。
4. 所有测试命令、退出码和准确结果。
5. 三领域评测结果。
6. Baseline fail-closed 验证结果。
7. SSE 异常审计验证结果。
8. 尚未解决的问题或风险。
9. 明确说明没有 commit 或 push。

完成后停止，等待 Codex 复审。

---
