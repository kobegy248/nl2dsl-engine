# NL2DSL Agent 能力增强设计

## 背景

当前 NL2DSL 的查询管道是线性的：用户输入 → clarification → decompose → generate → validate → ... → execute → verify。每个查询只生成并执行一条 DSL。

当用户提出复杂问题时（如"对比今年和去年华东销售额"），现有管道只能将其改写成单条 DSL（如按年分组），无法真正执行多步骤分析（分别查两年数据再计算增长率）。

本设计引入 Agent 编排层，将 NL2DSL 从"单 DSL 查询引擎"升级为"多步骤数据分析 Agent"。

## 目标

1. **任务规划**：识别用户意图类型，将复杂问题分解为多个子查询
2. **置信度评估**：评估生成 DSL 的质量，低置信度时主动澄清
3. **反馈闭环**：消费用户纠错反馈，持续优化 RAG 和术语映射
4. **解释生成**：返回自然语言解释，让用户理解系统如何理解其问题

## 非目标

- **用户偏好记忆**：本次迭代不实现（推迟到后续迭代）
- **多模态交互**：不涉及语音、图表生成等
- **外部工具调用**：不引入除 SQL 执行外的新工具

## 架构概述

```
用户请求
  ↓
API 入口 (/api/v1/query 或 /query/stream)
  ↓
Agent 编排层（新增）
  ├── plan：意图识别 + 任务分解
  │     ↓
  │   [简单查询] ──→ 直接走单 DSL 管道
  │   [复杂查询] ──→ dispatch 调度子查询 → aggregate 合并结果
  │
  ├── confidence：DSL 置信度评分
  ├── explain：生成自然语言解释
  └── feedback：记录并消费用户反馈
  ↓
SSE 流式返回（每步 push 到客户端）
```

Agent 编排层不替换现有单 DSL 管道，而是将其作为"工具"复用。每个子查询仍然走完整的 clarification → decompose → generate → validate → permission → build → scan → sandbox → execute 流程。

## 组件设计

### 1. plan 节点（意图识别 + 任务分解）

**位置**：内嵌到 `build_graph`，在 `clarification` 之后。

**输入**：`question` + `registry_dict`
**输出**：`Plan` 对象

**意图分类**（渐进式：LLM 优先，无 LLM 时降级为关键词规则）：

| 意图 | 关键词 | 子查询数 | 合并方式 |
|------|--------|---------|---------|
| `single_query` | "查一下"、单维度 | 1 | 直接返回 |
| `compare` | "对比"、"同比"、"和...比" | 2 | 计算差值/增长率 |
| `trend` | "趋势"、"走势"、"变化" | N | 按时间序列排序 |
| `correlation` | "关联"、"影响" | 2+ | 相关系数 |

**Plan 模型**：

```python
class SubQuery:
    id: str
    dsl: dict | None       # 初始为 None，由 generate_dsl 填充
    depends_on: list[str]  # 空列表表示可并行
    description: str       # "今年华东销售额"

class Plan:
    intent: str            # 意图类型
    sub_queries: list[SubQuery]
    reasoning: str         # LLM 推理过程（用于 explain）
    requires_approval: bool  # 是否需用户确认（预留，默认 False）
```

**路由逻辑**：
- `intent == "single_query"` → 路由到 `decompose`，走原管道
- `intent != "single_query"` → 路由到 `AgentOrchestrator.dispatch`

### 2. dispatch 节点（子查询调度）

**位置**：新增 `agent/dispatcher.py`，被 `api_factory.py` 调用。

**串行 vs 并行决策**：
- 子查询间无依赖（如"对比华东和华南"）→ `asyncio.gather` 并行执行
- 子查询间有依赖（如"销售额前10的产品中哪些是新品"）→ 串行执行

**执行方式**：每个子查询调用 `DomainContext.graph.ainvoke()`（复用现有管道）。子查询 DSL 直接在 state 中构造，跳过 clarification（避免重复追问）。

### 3. aggregate 节点（结果合并）

**位置**：新增 `agent/aggregator.py`。

**合并策略**：

```python
def aggregate(results: list[QueryResult], intent: str) -> dict:
    if intent == "compare":
        a, b = results[0].data, results[1].data
        return {
            "rows": a + b,
            "comparison": {"diff": b[0]["sales_amount"] - a[0]["sales_amount"],
                         "growth_rate": f"{(b[0]['sales_amount'] / a[0]['sales_amount'] - 1) * 100:.1f}%"}
        }
    if intent == "trend":
        return {"rows": list(chain.from_iterable(r.data for r in results)),
                "trend": "up" if results[-1].data[0]["sales_amount"] > results[0].data[0]["sales_amount"] else "down"}
```

### 4. confidence 节点（置信度评估）

**位置**：内嵌到 `build_graph`，在 `build_sql` 之前。

**评估维度**：

1. **语法置信度**（100% 规则）：`DSLValidator.validate()` 是否通过
2. **语义置信度**（LLM）：LLM 判断"此 DSL 是否回答了用户问题"
3. **历史置信度**（规则）：该 DSL 结构是否在历史成功查询中出现过

**综合评分**：
```
confidence = min(语法 ? 100 : 0, 语义评分) * 历史权重
```

**路由决策**：
- `>= 80`：继续执行
- `60-79`：继续执行，附加 warning
- `< 60`：路由到 `explain` 节点，生成澄清追问

### 5. explain 节点（解释生成）

**位置**：内嵌到 `build_graph`，在 `verify_dsl` 之后。

**输出**：自然语言解释字符串，如：
> "您的问题是'对比今年和去年华东销售额'。我将其分解为两个子查询：查询 2024 年华东地区销售额、查询 2025 年华东地区销售额。2025 年销售额为 1,200 万元，同比增长 15.3%。"

**生成方式**：LLM 基于 `Plan.reasoning` + 执行结果生成。无 LLM 时返回预置模板。

### 6. feedback processor（反馈闭环）

**位置**：新增 `agent/feedback_processor.py`，由 Engine 启动时注册为后台任务。

**消费逻辑**：
1. 定期读取 `feedback.jsonl`（或通过 API 读取）
2. 提取高频纠正模式（如 10 次纠正"流水"→`gmv`）
3. 自动增强 `terms.yaml` 中的映射权重
4. 更新 RAG 向量库中对应记录的权重

**与现有组件的关系**：
- 读取 `FeedbackCollector` 的输出
- 写入 `SemanticRegistry` 和 `MilvusLiteStore`

## 数据模型

### AgentState

新增状态类型，用于 Agent 编排层内部：

```python
class AgentState(TypedDict):
    question: str
    user_id: str
    tenant_id: str
    domain: str

    plan: Plan | None
    sub_results: dict[str, QueryResult]  # sub_query_id -> 结果
    final_result: dict | None

    confidence: float
    explanation: str | None
    status: str  # "planning" | "executing" | "aggregating" | "done"
    trace: list[dict]
```

### QueryState 扩展

现有 `QueryState` 新增字段：
- `confidence: float` — DSL 生成后的置信度
- `explanation: str` — 执行后的解释文本

## API 变更

### SSE 新增事件类型

`/api/v1/query/stream` 新增以下事件：

```
event: plan
data: {"intent": "compare", "reasoning": "...", "sub_queries": [{"id": "sq_1", "description": "今年华东销售额"}, ...]}

event: sub_query_start
data: {"sub_query_id": "sq_1", "description": "今年华东销售额"}

event: sub_query_result
data: {"sub_query_id": "sq_1", "row_count": 5, "status": "success"}

event: aggregate
data: {"type": "compare", "metrics": {"growth_rate": "15.3%"}}

event: confidence
data: {"score": 85, "syntax": 100, "semantic": 90}

event: explain
data: {"text": "我查询了2024和2025年华东地区的销售额..."}
```

### 新增内部 API

```python
# agent/orchestrator.py
class AgentOrchestrator:
    async def run(self, question: str, user_id: str, tenant_id: str, domain: str) -> AgentResult:
        """完整 Agent 执行流程。"""

    async def plan(self, question: str, registry_dict: dict) -> Plan:
        """意图识别 + 任务分解。"""

    async def dispatch(self, plan: Plan, domain_context: DomainContext) -> dict[str, QueryResult]:
        """调度子查询执行。"""

    def aggregate(self, results: dict[str, QueryResult], plan: Plan) -> dict:
        """合并子查询结果。"""
```

## 与现有管道的集成

| 组件 | 集成方式 | 文件 |
|------|---------|------|
| plan 节点 | `build_graph` 新增节点，在 `clarification` 之后 | `graph/nodes.py` |
| confidence 节点 | `build_graph` 新增节点，在 `build_sql` 之前 | `graph/nodes.py` |
| explain 节点 | `build_graph` 新增节点，在 `verify_dsl` 之后 | `graph/nodes.py` |
| Agent 编排器 | 新增模块，在 `api_factory.py` 中调用 | `agent/orchestrator.py` |
| feedback processor | 新增后台任务，Engine 启动时注册 | `agent/feedback_processor.py` |
| dispatch | 调用 `DomainContext.graph.ainvoke()` 执行子查询 | `agent/dispatcher.py` |

## 存储方案

复用现有 SQLite（`audit_log` 所在数据库），新增一张表：

```sql
-- feedback 消费记录（避免重复处理）
CREATE TABLE feedback_processed (
    query_id TEXT PRIMARY KEY,
    correction_type TEXT,     -- "metric_alias" | "dimension" | "filter"
    original_value TEXT,
    corrected_value TEXT,
    processed_at TIMESTAMP
);
```

## 测试策略

1. **plan 节点测试**：验证意图分类正确性（对比/趋势/单查询）
2. **dispatch 测试**：验证并行/串行调度逻辑
3. **aggregate 测试**：验证增长率、趋势计算正确
4. **confidence 测试**：验证评分阈值路由（<60 触发澄清）
5. **feedback processor 测试**：验证高频纠正模式提取
6. **E2E 测试**：完整 Agent 流程（对比查询 → 子查询执行 → 合并结果）

## 实现顺序

1. **plan 节点**（含意图分类 + 子查询分解）
2. **confidence 节点**（含语法/语义评估）
3. **dispatch + aggregate**（子查询调度和结果合并）
4. **explain 节点**（解释生成）
5. **feedback processor**（反馈闭环消费端）
6. **SSE 事件扩展**（新增事件类型）
7. **E2E 测试**

## 风险

- **子查询并行执行**：可能耗尽数据库连接池，需限制并发数（max 3 个并行子查询）
- **plan 节点 LLM 延迟**：增加一次 LLM 调用，简单查询也有额外开销（约 200-500ms）
- **aggregate 结果格式**：合并后的结果格式可能与现有前端不兼容，需同步更新前端
