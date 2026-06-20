# Claude 修复提示词：第五周第三轮审阅整改

将下面整段内容交给 Claude：

---

你现在负责继续修复 NL2DSL 项目第五周功能在第三轮代码审阅中发现的问题。

项目目录：

```text
D:\demo\db-gpt\NL2DSL
```

## 开始前必须阅读

按顺序阅读：

1. `AGENTS.md`
2. `CLAUDE.md`
3. `docs/specs/2026-06-19-week5-quality-feedback-observability-design.md`
4. `docs/superpowers/plans/2026-06-19-week5-review-fix-prompt.md`
5. `docs/superpowers/plans/2026-06-19-week5-second-review-fix-prompt.md`
6. `docs/reports/2026-06-19-week5-review-checklist.md`
7. 当前未提交修改
8. 以下真实失败报告：
   - `reports/v2_bank/benchmark_report.json`
   - `reports/v2_sc/benchmark_report.json`
   - `reports/v2_rule_off/benchmark_report.json`

不要回退或覆盖已有修改。先使用 Codegraph 追踪完整调用链。

## 工作方式

- 这是第三轮定向整改，不要重写第五周功能。
- 对 LangGraph 递归问题必须先执行系统化根因分析，禁止直接提高 `recursion_limit` 掩盖死循环。
- 使用 TDD：先添加能复现问题的失败测试，再修改实现。
- 不得删除、跳过或弱化现有测试。
- 不得把异常结果改成 unavailable、warning 或 success 来制造通过。
- 由你负责运行全部相关测试及真实三领域评测。
- 不要自行 commit 或 push，完成后等待 Codex 复审。

## P0：修复 bank 与 supply_chain 的 LangGraph 无限递归

### 已确认事实

真实报告显示：

```text
bank:         0/10 passed
supply_chain: 0/10 passed
```

全部用例出现：

```text
GRAPH_RECURSION_LIMIT
Recursion limit of 10007 reached without hitting a stop condition
```

单条用例耗时约 15 秒。

相关报告：

```text
reports/v2_bank/benchmark_report.json
reports/v2_sc/benchmark_report.json
```

### 根因调查要求

修复前必须先完成以下调查并在最终回复中说明证据：

1. 选择 bank 和 supply_chain 各一个最小失败用例。
2. 记录每次 LangGraph 节点跳转和 `dsl_attempts` 变化。
3. 确认循环发生在哪组节点或条件边，例如：
   - generate_dsl
   - validate_dsl
   - correct_dsl
   - simplify_dsl
   - execute_sql
4. 检查 `route_after_validate()`、`route_after_execute()` 等路由函数的重试计数是否真的增长。
5. 检查 `Annotated` reducer 与节点返回值是否导致 attempts 被覆盖、重复或永远为空。
6. 比较 ecommerce 成功路径与 bank/supply_chain 失败路径的配置、DSL、验证错误和权限注入差异。
7. 确认 rule generator 是否仍包含 ecommerce 硬编码指标、维度或 data_source。

禁止把 `recursion_limit` 从 10007 改得更大作为修复。

### 修复要求

1. 任一校验或执行重试必须有明确、可证明增长的计数。
2. 达到最大尝试次数后必须进入终止 error 节点。
3. 不允许任何错误路径无限回到自身。
4. bank 和 supply_chain 的 rule generator 必须使用各自 registry：
   - 不发明 ecommerce 指标。
   - 不发明 ecommerce 维度。
   - 使用对应领域合法 data_source。
5. 不可修复的 DSL 必须快速失败，不能运行 15 秒后撞 recursion limit。
6. 错误响应和 Audit 必须保留最后一次明确失败原因。
7. 目标不是让错误消失，而是让真实合法用例能生成该领域合法 DSL 并完成执行。

必须新增测试：

- bank 最小查询在有限节点步数内结束。
- supply_chain 最小查询在有限节点步数内结束。
- 持续校验失败时达到最大重试次数后终止。
- 持续 SQL 执行失败时达到最大重试次数后终止。
- `dsl_attempts` 每次重试都增加。
- 不出现 `GRAPH_RECURSION_LIMIT`。
- bank actual DSL 的 metric、dimension、data_source 均来自 bank registry。
- supply_chain actual DSL 的对应字段均来自 supply-chain registry。

### 真实验收标准

修复后必须重新运行：

```powershell
.\.venv\Scripts\python.exe -m nl2dsl.evaluation.v2_cli `
  --generator rule --optimizer off --domain bank `
  --output reports/v2_bank

.\.venv\Scripts\python.exe -m nl2dsl.evaluation.v2_cli `
  --generator rule --optimizer off --domain supply_chain `
  --output reports/v2_sc
```

硬性验收：

- 两个命令退出码均为 0。
- 两份报告中 `GRAPH_RECURSION_LIMIT` 出现次数均为 0。
- 不允许继续出现 0/10 全部运行错误。
- 每个领域至少有一个用例真实执行成功。
- 每条用例不得出现约 15 秒的死循环延迟。
- 报告 JSON 必须可被标准 JSON parser 解析。

如果准确率仍不理想，可以作为后续语义质量问题记录；但运行链路必须正常终止并产生真实 DSL、SQL、Trace 或明确有限错误。

## P1：同步修复 Web 审计页面 tenant_id 契约

### 当前问题

后端现在要求：

```text
GET /api/v1/admin/audit/queries?tenant_id=...
GET /api/v1/admin/audit/queries/{query_id}?tenant_id=...
```

但现有前端：

```text
web/src/api/audit.ts
web/src/hooks/useAudit.ts
```

没有传 tenant_id，审计列表和详情会直接失败。

### 修复要求

1. 审计 API 客户端的 list/detail 都必须接收 tenant_id。
2. React Query 的 queryKey 必须包含 tenant_id，避免跨租户缓存污染。
3. 页面必须从现有用户/租户上下文取得 tenant_id。
4. 如果项目尚无统一身份上下文，可以沿用 QueryPage 当前使用的租户来源，但不要在多个文件重复硬编码。
5. tenant_id 未就绪时不要发请求。
6. 切换租户后必须重新加载列表和详情。
7. 同步检查 Feedback 管理前端是否存在相同问题。

必须新增测试：

- audit list 请求包含 tenant_id。
- audit detail 请求包含 tenant_id。
- queryKey 包含 tenant_id。
- tenant_id 为空时查询 disabled。
- 切换 tenant_id 后发起新请求，不复用其他租户缓存。
- 页面不再因后端强制 tenant 参数而返回 400。

## P1：Agent Trace 完整率不得把 start 当作完成

### 当前问题

质量分析器把以下步骤都当作执行证据：

```text
sub_query_start
sub_query_end
```

因此只开始、从未结束的子查询也可能被判为完整。

现有 E2E 测试同样接受：

```python
steps & {"sub_query_end", "sub_query_start", ...}
```

### 修复要求

1. `sub_query_start` 只能证明开始，不能证明执行完成。
2. Agent 成功路径至少要求：
   - agent
   - plan
   - 每个已开始 subquery 都有匹配的 sub_query_end
   - aggregation 或 explanation
3. 成功状态下存在未闭合 subquery 时必须判为不完整。
4. error 状态可以有失败的 sub_query_end，但必须记录明确 status/error。
5. 最好按 sub_query_id 成对校验，而不是只检查步骤名称集合。
6. 普通复杂查询和复杂 SSE 使用同一套校验规则。

必须新增测试：

- 只有 `agent + sub_query_start` 判为不完整。
- start/end 数量不匹配判为不完整。
- sub_query_id 不匹配判为不完整。
- 完整成功路径判为完整。
- 带失败 sub_query_end 的 error 路径保留失败信息。
- 修改现有 E2E 断言，成功路径必须看到 `sub_query_end`，不能接受 start 替代。

## P1：评测基础设施故障必须返回非零退出码

### 当前问题

当前 V2 CLI 只有在 Baseline regression 且启用 `--fail-on-regression` 时返回 1。

即使所有用例都是：

```text
status=error
GRAPH_RECURSION_LIMIT
```

CLI 仍返回 0。

### 修复要求

1. 明确区分：
   - 语义评分未达阈值。
   - 用例正常失败。
   - 评测基础设施/执行链路异常。
2. 至少在以下情况返回非零退出码：
   - 所有选中用例均为 error。
   - 出现 `GRAPH_RECURSION_LIMIT`。
   - 报告无法生成或 JSON 无法解析。
   - 没有任何可评分结果。
3. 建议增加独立参数，例如：

```text
--fail-on-execution-error
```

默认行为应保守，不能把 100% 执行错误视为成功。
4. 报告 summary 增加 execution_errors 数量。
5. Markdown 明确区分评分失败与执行错误。
6. 不要把普通低分自动等同基础设施错误。

必须新增测试：

- 全部 execution error 时退出码非零。
- 出现 GRAPH_RECURSION_LIMIT 时退出码非零。
- 部分用例成功、部分语义低分时按参数和契约处理。
- 正常可评分运行返回 0。
- Baseline regression 逻辑保持不回退。

## P1：报告必须是严格合法 JSON

PowerShell `ConvertFrom-Json` 读取当前 bank/supply-chain 报告时失败。无论原因是乱码、截断还是未转义内容，报告都必须通过标准 JSON parser。

修复要求：

1. 使用 Python `json.load()` 验证所有生成报告。
2. 报告写入采用 UTF-8。
3. 不允许错误信息中的换行、控制字符破坏 JSON。
4. 建议原子写入，避免中途中断留下半文件。
5. CLI 生成后立即回读验证；失败则返回非零退出码。

必须新增测试：

- 含多行异常信息的报告可被 `json.load()` 解析。
- 中文 query/error 可正确读取。
- 写入中断不会覆盖上一份有效报告。

## P2：编码与清理

1. 修复本轮涉及文件中的乱码中文注释、docstring 和文档内容，统一 UTF-8。
2. 运行 `git diff --check`，必须无错误。
3. 不要做与上述问题无关的重构。
4. 正式运行代码不得依赖 `tests.*`。

## 测试责任

你的环境可以运行项目 `.venv`，请先确认：

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pytest --version
```

至少执行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/ -q
.\.venv\Scripts\python.exe -m pytest tests/evaluation/v2/ -q
.\.venv\Scripts\python.exe -m pytest tests/integration/ -q
.\.venv\Scripts\python.exe -m pytest `
  tests/e2e/test_feedback_audit_api.py `
  tests/e2e/test_api.py `
  tests/e2e/test_audit_query_api.py `
  tests/e2e/test_agent_coverage.py -q

cd web
npm test -- --run
npm run build
cd ..

git diff --check
```

还必须执行：

1. ecommerce rule/off 真实评测。
2. bank rule/off 真实评测。
3. supply_chain rule/off 真实评测。
4. 使用 Python `json.load()` 回读三份报告。
5. 构造全部 execution error 的评测，确认 CLI 非零退出。
6. 验证 Web 审计列表和详情请求都携带 tenant_id。

不得只提供“测试通过”。最终回复必须列出每条命令的：

- 退出码
- passed
- failed
- skipped
- 执行时间

## 文档同步

根据实际行为更新：

- `docs/evaluation/framework-guide.md`
- `docs/api/21-api-contract.md`
- `docs/audit/audit-log-design.md`
- `docs/specs/2026-06-05-next-stage-roadmap.md`

重点写清：

- Graph 重试终止条件。
- execution error 的 CLI 退出码。
- 报告 JSON 完整性保证。
- Web 审计 tenant_id 数据来源。
- Agent Trace start/end 配对规则。

正文使用中文，代码标识、命令和 API 字段保留英文。

## 完成后的回复格式

完成后提供：

1. LangGraph 无限递归根因及证据。
2. 按 P0/P1/P2 对照的修复摘要。
3. 修改文件列表。
4. 每个问题对应的测试文件和测试名称。
5. 所有测试命令、退出码及准确结果。
6. ecommerce/bank/supply_chain 三份真实评测摘要。
7. 三份 JSON 的 `json.load()` 验证结果。
8. Web 测试和构建结果。
9. 尚未解决的问题或风险。
10. 明确说明没有 commit 或 push。

完成后停止，等待 Codex 复审。

---
