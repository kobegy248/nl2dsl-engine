# 第五周设计：评估、反馈与可观测闭环

> 日期：2026-06-19
> 阶段目标：让每次语义能力改进都可被真实评估，让用户反馈可追溯到完整查询链路，并安全地沉淀为候选评测资产。

---

## 1. 背景与问题

NL2DSL 已完成复杂过滤、时间语义、隐式 JOIN、分组 TopN 和占比等能力建设。下一阶段不能继续只靠测试是否通过判断质量，需要建立版本级质量闭环。

当前实现存在以下关键缺口。

### 1.1 V2 Optimizer 对比不是真实运行

`V2BenchmarkRunner.run_batch_with_optimizer()` 当前会从测试用例的 `expected` 构造一份 DSL，再选择是否执行 Optimizer。

这意味着：

- Baseline 不是自然语言生成的实际 DSL。
- Optimized 也不是对实际生成结果进行优化。
- 评测结果无法衡量 NL → DSL 准确率。
- Optimizer ON/OFF 的差异可能被期望答案污染。

### 1.2 反馈无法自然关联查询

反馈 API 要求 `query_id`，但普通查询响应中没有返回 `query_id`。用户无法直接对刚完成的查询提交反馈。

此外，前端和后端的反馈模型目前不一致：

- 后端：`query_id / user_id / corrected_dsl / comment`
- 前端：`query_id / is_correct / issue_type / comment`

### 1.3 反馈和审计只有逻辑关联，没有可靠约束

当前反馈直接写入 `feedback.jsonl`：

- 不检查对应审计记录是否存在。
- 不检查反馈用户是否与查询用户一致。
- 没有租户隔离校验。
- 没有持久化去重。
- 无法高效联合查询审计 DSL、SQL、Trace 和反馈。

### 1.4 反馈不能安全转化为质量资产

现有 `FeedbackProcessor` 可以统计部分纠错模式，但不能：

- 将反馈关联原始问题和原始 DSL。
- 生成待人工审核的评测用例。
- 标记来源反馈和去重哈希。
- 防止未经审核的反馈自动修改 Prompt、RAG 或语义配置。

---

## 2. 设计原则

### 2.1 真实运行优先

评测必须调用真实查询链路获得 DSL、SQL、结果、Trace。禁止从 `expected` 构造 `actual_dsl`。

### 2.2 同输入矩阵对比

同一个测试用例需要支持以下矩阵：

| 生成模式 | Optimizer | 用途 |
|----------|-----------|------|
| rule | off | 无 LLM、无优化基线 |
| rule | on | 规则生成 + Optimizer 收益 |
| llm | off | LLM 原始语义能力 |
| llm | on | 完整生产链路能力 |

LLM 不可用时必须明确标记为 `unavailable` 或跳过，不能静默退化后仍声称是 LLM 模式。

### 2.3 反馈必须可追溯

每条反馈必须能追溯到：

- 原始自然语言问题
- 用户和租户
- 原始 DSL
- 最终 DSL
- SQL
- 执行结果摘要
- Trace
- 错误信息

### 2.4 人工审核后入库

用户反馈只能生成候选评测用例，不能自动：

- 修改 `configs/metrics.yaml`
- 修改 `configs/terms.yaml`
- 修改 Prompt
- 写入 RAG few-shot 集合
- 写入正式 Evaluation Dataset

候选用例必须经过人工审核后再进入正式评测集。

### 2.5 最少复制敏感数据

反馈表只保存关联 ID、用户纠正内容和必要元数据。原始 SQL、Trace、问题等继续以审计日志为数据源，不在反馈表重复保存。

---

## 3. 总体架构

```text
真实查询链路
    │
    ├── QueryResponse 返回 query_id
    │
    ├── AuditLogger 保存 DSL / SQL / Trace / 状态
    │
    └── EvaluationRunner 收集 Observation
             │
             ▼
       Baseline / Matrix Report
             │
             ▼
       Regression Gate

用户反馈
    │
    ▼
Feedback API
    │ 校验 query_id / user_id / tenant_id
    ▼
FeedbackStore（与 Audit 共用数据库）
    │
    ├── Feedback + Audit 联合查询
    ├── 问题模式统计
    └── Candidate Exporter
             │
             ▼
    reports/feedback/candidates.yaml
             │
             ▼
          人工审核
             │
             ▼
    tests/evaluation/dataset/...
```

---

## 4. 真实评测执行模型

### 4.1 EvaluationObservation

新增统一的运行观测对象：

```python
@dataclass
class EvaluationObservation:
    case_id: str
    domain: str
    generator_mode: str       # rule | llm
    optimizer_enabled: bool
    status: str               # success | warning | clarification | error | unavailable
    query_id: str | None
    dsl_before_optimizer: dict | None
    dsl_after_optimizer: dict | None
    sql: str | None
    data: list[dict] | None
    trace: list[dict]
    error: str | None
    execution_time_ms: int
```

评分器只读取真实 Observation 中的最终 DSL 和治理信息。

### 4.2 执行适配器

定义执行协议：

```python
class EvaluationExecutor(Protocol):
    def execute(
        self,
        case: V2TestCase,
        *,
        generator_mode: str,
        optimizer_enabled: bool,
    ) -> EvaluationObservation:
        ...
```

建议提供：

- `ApiEvaluationExecutor`：通过 FastAPI TestClient 调用真实 API。
- 测试用 `FakeEvaluationExecutor`：返回固定 Observation。

### 4.3 Optimizer 开关

`create_app()` 或 Graph 构建入口增加显式开关：

```python
enable_optimizer: bool = True
```

Optimizer OFF 时：

- Graph 中不注册 `optimize_dsl` 节点。
- Trace 中明确记录 Optimizer disabled 或不存在该节点。
- 不能运行 Optimizer 后再伪装为 OFF。

### 4.4 生成模式

建议 `create_app()` 增加：

```python
generator_mode: Literal["rule", "llm"] = "llm"
```

- `rule`：强制使用 RuleBasedDSLGenerator。
- `llm`：强制使用 LLM；没有 LLM Client 时返回 `unavailable`，不静默使用规则生成器。

生产默认行为保持兼容，可在评测执行器中显式控制模式。

---

## 5. 数据集与多领域

### 5.1 V2TestCase 增加 domain

```python
@dataclass
class V2TestCase:
    id: str
    query: str
    domain: str = "ecommerce"
    ...
```

领域解析优先级：

1. 单个测试用例的 `domain`
2. YAML 顶层 `domain`
3. 数据集目录名
4. 默认 `ecommerce`

### 5.2 CLI 过滤

V2 CLI 增加：

```text
--domain ecommerce
--tags filter,time
--generator rule|llm|all
--optimizer on|off|all
```

### 5.3 报告分组

固定报告至少包含：

- 总体分数
- 按 domain 分数
- 按 tag 分数
- 按 generator / optimizer 运行模式分数
- 失败用例
- 相比 baseline 的回退用例
- 延迟统计
- Optimizer Fix / Warn / Reject 统计

---

## 6. Baseline 与回归门禁

### 6.1 Baseline 文件

建议格式：

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-06-19T10:00:00+08:00",
  "git_commit": "abc1234",
  "dataset_hash": "...",
  "matrix": {
    "generator": "rule",
    "optimizer": "on"
  },
  "summary": {},
  "cases": {}
}
```

### 6.2 CLI

```bash
python -m nl2dsl.evaluation.v2_cli \
  --dataset tests/evaluation/dataset/v2 \
  --generator rule \
  --optimizer on \
  --save-baseline reports/baselines/rule-optimizer-on.json
```

回归对比：

```bash
python -m nl2dsl.evaluation.v2_cli \
  --dataset tests/evaluation/dataset/v2 \
  --generator rule \
  --optimizer on \
  --baseline reports/baselines/rule-optimizer-on.json \
  --fail-on-regression
```

### 6.3 门禁规则

默认规则：

- Overall 不得下降。
- 任一评分维度下降超过 2 个百分点则失败。
- 新增失败用例则失败。
- 单用例分数下降超过 10 个百分点则失败。
- `unavailable` 不算通过。

阈值应支持 CLI 配置，但默认值必须保守。

---

## 7. 查询与反馈契约

### 7.1 QueryResponse 返回 query_id

以下响应都需要返回 `query_id`：

- `/api/v1/query`
- `/api/v1/query/dsl`
- `/api/v1/query/execute`
- SSE 最终 `result` 事件

字段为向后兼容的新增字段：

```json
{
  "query_id": "uuid",
  "status": "success",
  "data": []
}
```

### 7.2 统一 FeedbackRequest

建议请求：

```json
{
  "query_id": "uuid",
  "user_id": "u001",
  "tenant_id": "t001",
  "is_correct": false,
  "issue_type": "metric",
  "corrected_dsl": {},
  "comment": "销售额口径不正确"
}
```

`issue_type` 枚举：

- `intent`
- `metric`
- `dimension`
- `filter`
- `time`
- `join`
- `ranking`
- `proportion`
- `permission`
- `result`
- `other`

### 7.3 提交校验

反馈写入前必须：

1. 查询审计记录存在。
2. `user_id` 与审计记录一致。
3. `tenant_id` 与审计记录一致。
4. `corrected_dsl` 存在时通过 DSL Schema 校验。
5. 至少提供 `is_correct=false`、`corrected_dsl` 或非空 `comment` 中的一项有效反馈。

---

## 8. FeedbackStore

### 8.1 存储选择

正式运行使用与审计日志相同的 SQLAlchemy Engine，创建：

```sql
CREATE TABLE IF NOT EXISTS nl2dsl_feedback (
    feedback_id TEXT PRIMARY KEY,
    query_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    is_correct INTEGER NOT NULL,
    issue_type TEXT,
    corrected_dsl TEXT,
    comment TEXT,
    dedup_hash TEXT NOT NULL UNIQUE,
    review_status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

不依赖数据库外键特性，应用层校验 `query_id`。

### 8.2 去重

`dedup_hash` 使用以下内容的稳定 JSON 计算 SHA-256：

```text
query_id + user_id + tenant_id + is_correct + issue_type + corrected_dsl + comment
```

重复提交返回原 `feedback_id`，不重复插入。

### 8.3 兼容策略

保留现有 JSONL Collector 作为兼容适配器或测试工具，但 API 默认使用数据库 FeedbackStore。

---

## 9. 反馈转候选评测用例

### 9.1 Candidate Exporter

新增命令：

```bash
python -m nl2dsl.feedback.exporter \
  --output reports/feedback/candidates.yaml \
  --status pending
```

输出示例：

```yaml
candidates:
  - candidate_id: feedback_xxx
    review_status: pending
    source_feedback_ids: [fb-1, fb-2]
    domain: ecommerce
    query: "查询各品类销售额占比"
    original_dsl: {}
    expected:
      metric: sales_amount
      dimensions: [category]
      planner:
        post_process:
          type: proportion
          metric: sales_amount
    issue_type: proportion
```

### 9.2 约束

- 仅 `corrected_dsl` 非空的负反馈可直接生成候选 DSL。
- 只有 comment 的反馈进入“待分析”列表，不猜测 expected DSL。
- 相同 query + corrected DSL 合并来源反馈 ID。
- Exporter 不写正式 dataset。

---

## 10. 可观测质量报告

新增固定格式质量报告，将 Evaluation、Audit、Feedback 三类信息汇总。

### 10.1 指标

Evaluation：

- Overall / 各维度分数
- Domain / Tag 分数
- 回退用例数量
- Optimizer 平均 Fix / Warn / Reject

Audit：

- 查询总数
- success / warning / clarification / error 分布
- P50 / P95 延迟
- Trace 完整率
- DSL / SQL / audit 字段完整率

Feedback：

- 反馈总数
- 负反馈率
- 审计关联率
- issue_type Top N
- corrected_dsl 覆盖率
- 候选评测用例数量

### 10.2 Trace 完整率

按实际路径检查，不要求所有查询都有完全相同节点。

简单成功路径至少包含：

```text
generate_dsl / validate_dsl / resolve_semantic /
build_sql / scan_sql / execute_sql
```

如果 Optimizer 开启，则还应包含 `optimize_dsl`。

Clarification 路径只要求 clarification 和终止状态。

复杂 Agent 路径要求 agent / sub-query 级关键信息，不能用简单路径节点硬套。

---

## 11. 本阶段不做

- 不做自动 Prompt 优化。
- 不自动写语义配置。
- 不自动写 RAG 集合。
- 不做完整反馈统计前端面板。
- 不引入外部可观测平台。
- 不将用户反馈直接视为正确答案。

---

## 12. 验收标准

- V2 Runner 不再从 expected 构造 actual DSL。
- 一条命令可运行真实 rule/LLM × optimizer ON/OFF 矩阵。
- LLM 不可用时不会伪装成 LLM 评测结果。
- QueryResponse 和 SSE 返回 query_id。
- 反馈写入前校验审计、用户和租户。
- 重复反馈不会重复入库。
- 反馈可联合查询审计详情。
- 可导出待人工审核的候选评测 YAML。
- 可生成固定格式质量报告。
- Baseline 回退可使 CLI 返回非零退出码。
- 新增功能有单元、集成和 E2E 测试。
