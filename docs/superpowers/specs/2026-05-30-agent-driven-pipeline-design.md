# Agent-Driven Pipeline 设计文档

> 让 Agent 成为 NL2DSL 的核心决策中枢，从"固定管道"升级为"动态决策"。

---

## 1. 背景与目标

### 1.1 当前问题

当前 NL2DSL 的 Agent 层能力薄弱：

- **Planner**：仅支持 4 种硬编码意图（compare/trend/correlation/single_query），关键词匹配，无法处理复合意图
- **Aggregator**：仅支持 3 种聚合策略（diff/trend_direction/Pearson），新增分析类型需改代码
- **异常处理**：子查询失败只有"全成功"或"全失败"两种结果，没有恢复机制
- **扩展性**：新增意图 = 改 Planner prompt + 改 Aggregator 代码 + 改路由逻辑，三处联动

### 1.2 设计目标

1. **意图无限扩展**：新增意图只需改 YAML 配置，不改代码（90%场景）
2. **动态任务分解**：LLM 根据查询内容决定拆几个、怎么拆、谁依赖谁
3. **异常自动恢复**：子查询失败时自动重试/降级/跳过，返回部分结果
4. **治理服务按需调用**：Agent 根据查询内容动态加载需要的治理服务，非全量加载
5. **全链路可追溯**：每个节点记录输入输出，失败时可定位根因

---

## 2. 高层架构

### 2.1 架构图

```
用户输入
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│  AgentController（代码控制，确定性）                         │
│  ─────────────────────────────────────────                  │
│  1. 查 Memory（相似度 > 0.9 → 直接复用）                     │
│  2. 提取 Entities（关键词）                                  │
│  3. 按特征路由：                                             │
│     ├── 简单查询 ──► DirectExecutor                         │
│     ├── 复杂查询 ──► Planner                                │
│     └── 探索查询 ──► Explorer                               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Planner（LLM + 配置）                                        │
│  ───────────────────────────                                │
│  输入：问题 + Entities + 可用指标/维度清单                     │
│  输出：Plan（intent + sub_queries + aggregation）            │
│                                                             │
│  可扩展：新增意图只需改 configs/intents.yaml                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  EntityResolver（规则表查字典，确定性）                      │
│  ─────────────────────────────────────                      │
│  "销售额" ──► metrics.sales_amount                          │
│  "华东"   ──► dimensions.region = HD                        │
│  同一张表，永远同一结果                                      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Dispatcher（代码控制）                                       │
│  ─────────────────────────                                  │
│  1. 按需加载治理服务（MetricService / DimensionService）      │
│  2. 独立子查询并行（Semaphore=3），依赖子查询串行             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  SubQueryAgent（工具调用）                                    │
│  ───────────────────────────                                │
│  每个子查询走 LangGraph 工具链：                              │
│  RAG → Generate DSL → Validate → Permission → Resolve       │
│  → Confidence → Build SQL → Scan → Sandbox → Execute        │
│  → Verify → Explain                                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  RecoveryAgent（异常恢复）                                    │
│  ─────────────────────────                                  │
│  子查询失败时按策略恢复：                                     │
│  超时 → 加 LIMIT 重试 / 简化 DSL 重试 / 返回缓存             │
│  DSL 失败 → 简化 prompt 重试 / fallback mock / 跳过          │
│  权限拒绝 → 去掉敏感字段重试 / 跳过                          │
│  空结果 → 扩大时间范围 / 放宽条件 / 返回提示                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Aggregator（配置化策略）                                     │
│  ─────────────────────────                                  │
│  按 Plan.aggregation 选择聚合策略（插件注册表）：              │
│  diff / trend_direction / pearson / proportion / ranking    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Explainer（结果解释）                                        │
│  ───────────────────────                                    │
│  生成自然语言解释 + 子查询质量提示                             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  AuditLogger（全链路追溯）                                    │
│  ───────────────────────                                    │
│  SQLite 表记录：query_id / trace_json / dsl_json / sql_text │
│  每个节点输入输出完整记录，失败时详细记录                      │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 设计原则

| 原则 | 说明 |
|------|------|
| **确定性 vs 灵活性分层** | 外层控制流用代码（AgentController、Dispatcher），内层工具调用可用 LangGraph |
| **治理映射确定性** | 自然语言 → 治理服务的映射走规则表（代码字典），不走 LLM |
| **配置驱动扩展** | 意图定义在 YAML 中，分解/聚合策略在代码插件中注册 |
| **失败降级而非阻断** | 子查询失败优先恢复，无法恢复则跳过并标注，不阻断整个查询 |
| **全链路可追溯** | 每个节点记录输入输出，trace 树形嵌套，支持审计和故障排查 |

---

## 3. 模块设计

### 3.1 AgentController

**职责**：分析查询特征，决定执行路径。

**为什么用代码而非 LLM**：
- "单指标+单维度"是确定性判断（数 entities 个数）
- LLM 有随机性、延迟高、不好调试

```python
class AgentController:
    async def route(self, question: str, user_ctx: dict) -> ExecutionPlan:
        # 1. 查历史缓存
        if cached_plan := await self.memory.get_similar(question):
            return cached_plan

        # 2. 提取 entities
        entities = await self.extract_entities(question)

        # 3. 按特征路由（纯代码规则）
        if len(entities.metrics) == 1 and len(entities.dimensions) <= 1:
            return SimpleExecutionPlan(question, entities)
        elif entities.has_comparison_marker():
            return await self.planner.plan(question, entities)
        else:
            return ExplorationPlan(question, entities)
```

**输出**：

```python
class ExecutionPlan(ABC):
    """执行计划基类"""

class SimpleExecutionPlan(ExecutionPlan):
    """简单查询：不走子查询，直接生成 DSL 执行"""
    question: str
    entities: Entities

class ComplexExecutionPlan(ExecutionPlan):
    """复杂查询：需要拆解、并行、聚合"""
    question: str
    plan: Plan

class ExplorationPlan(ExecutionPlan):
    """探索性查询：多轮迭代，允许修正"""
    question: str
    exploration_steps: list[str]
```

---

### 3.2 Planner

**职责**：LLM 动态规划，生成 Plan（意图 + 子查询 + 聚合策略）。

#### 3.2.1 LLM Prompt

```
你是一个数据分析查询规划专家。

【用户问题】
{question}

【已提取的关键词】
指标: {entities.metrics}
维度: {entities.dimensions}
时间: {entities.time_range}

【当前域可用的指标】
{registry.metrics}

【当前域可用的维度】
{registry.dimensions}

【任务】
分析用户意图，生成执行计划。

【可用的意图类型】
{intent_descriptions}

【可用的分解策略】
- split_by_objects: 按对比对象拆分
- single_with_time_grouping: 单查询+时间分组
- total_plus_groups: 总计+分组
- sequential: 按步骤拆分（有依赖）

【可用的聚合策略】
- diff: 计算差异
- trend_direction: 检测趋势方向
- pearson: Pearson 相关系数
- proportion: 计算占比
- ranking: 排名取 TopN

【输出格式】
只输出 JSON：
{
  "intent": "compare",
  "sub_queries": [
    {"id": "sq-1", "description": "...", "depends_on": []},
    {"id": "sq-2", "description": "...", "depends_on": []}
  ],
  "aggregation": "diff",
  "reasoning": "...",
  "entities_used": ["销售额", "华东", "华南"]
}
```

#### 3.2.2 输出结构

```python
class Plan(BaseModel):
    intent: str
    sub_queries: list[SubQuery]
    aggregation: str
    reasoning: str
    entities_used: list[str]

class SubQuery(BaseModel):
    id: str
    description: str
    depends_on: list[str] = []
    dsl: dict | None = None
```

#### 3.2.3 Fallback 机制

```python
class Planner:
    async def plan(self, request: PlanRequest) -> Plan:
        try:
            return await self._llm_plan(request)
        except (LLMError, ParseError) as e:
            logger.warning("LLM plan failed: %s, falling back to rules", e)
            return self._rule_based_plan(request)  # 回退到关键词规则
```

#### 3.2.4 意图配置表

```yaml
# configs/intents.yaml
intents:
  compare:
    keywords: ["对比", "比较", "vs", "相比", "同比", "环比"]
    decomposition: "split_by_objects"
    aggregation: "diff"
    description: "对比多个对象的指标值"

  trend:
    keywords: ["趋势", "走势", "变化", "增长", "下降"]
    decomposition: "single_with_time_grouping"
    aggregation: "trend_direction"
    description: "分析指标随时间的变化趋势"

  proportion:
    keywords: ["占比", "构成", "贡献度"]
    decomposition: "total_plus_groups"
    aggregation: "proportion"
    description: "分析各部分占总体的比例"

  ranking:
    keywords: ["排名", "Top", "第几"]
    decomposition: "single_with_ordering"
    aggregation: "ranking"
    description: "按指标值排序取 TopN"

  sequential:
    keywords: ["先查", "然后", "再查"]
    decomposition: "sequential"
    aggregation: "sequential_filter"
    description: "按步骤递进查询，后续步骤依赖前面结果"

  drilldown:
    keywords: ["下钻", "明细", "展开"]
    decomposition: "drilldown"
    aggregation: "hierarchy_expand"
    description: "从汇总下钻到明细"
```

**新增意图 = 改 YAML，不改代码**（如果复用已有分解/聚合策略）。

---

### 3.3 EntityResolver（规则表）

**职责**：自然语言关键词 → 治理服务的确定性映射。

**为什么不用 LLM**：
- "销售额"必须永远映射到 `sales_amount`
- LLM 有随机性，两次查询可能映射到不同指标
- 数据治理要求一致性、可审计

```python
class EntityResolver:
    def __init__(self, registry: SemanticRegistry):
        self.registry = registry

    def resolve(self, plan: Plan) -> dict[str, ResolvedEntity]:
        """把 Plan 中的自然语言关键词映射到具体治理服务"""
        resolved = {}
        for sq in plan.sub_queries:
            resolved[sq.id] = {
                "metrics": self._resolve_metrics(sq.description),
                "dimensions": self._resolve_dimensions(sq.description),
                "data_source": self._resolve_data_source(sq.description),
            }
        return resolved

    def _resolve_metrics(self, text: str) -> list[str]:
        """查规则表：text 中的关键词对应哪个 metric"""
        for metric_id, info in self.registry.metrics.items():
            if info["description"] in text or metric_id in text:
                return [metric_id]
        return []
```

**规则表来源**：`configs/metrics.yaml`、`configs/dimensions.yaml`。

---

### 3.4 Dispatcher

**职责**：子查询调度，独立并行、依赖串行。

```python
MAX_PARALLEL_SUB_QUERIES = 3

async def dispatch_sub_queries(
    sub_queries: list[SubQuery],
    domain_context: DomainContext,
    base_state: dict,
) -> dict[str, QueryResult]:
    # 分离独立和依赖子查询
    independent = [sq for sq in sub_queries if not sq.depends_on]
    dependent = [sq for sq in sub_queries if sq.depends_on]

    # Phase 1: 独立子查询并行（Semaphore 限流）
    semaphore = asyncio.Semaphore(MAX_PARALLEL_SUB_QUERIES)
    async def _run_with_limit(sq):
        async with semaphore:
            return await _execute_sub_query(sq, domain_context, base_state)

    independent_results = await asyncio.gather(*(_run_with_limit(sq) for sq in independent))

    # Phase 2: 依赖子查询串行（拓扑排序）
    results = {r.sub_query_id: r for r in independent_results}
    remaining = list(dependent)
    while remaining:
        ready = [sq for sq in remaining if all(d in results for d in sq.depends_on)]
        if not ready:
            break  # 循环依赖或缺失
        for sq in ready:
            result = await _execute_sub_query(sq, domain_context, base_state)
            results[sq.id] = result
        remaining = [sq for sq in remaining if sq not in ready]

    return results
```

---

### 3.5 RecoveryAgent

**职责**：子查询失败时的自动恢复。

#### 3.5.1 恢复策略配置

```yaml
# configs/recovery_policies.yaml
recovery_policies:
  dsl_generation_failed:
    - action: simplify_prompt_retry
      max_attempts: 2
    - action: fallback_to_mock
    - action: skip_with_warning

  execution_timeout:
    - action: limit_retry
      limit: 100
    - action: simplify_dsl_retry
    - action: return_cached

  permission_denied:
    - action: remove_sensitive_fields_retry
    - action: skip_with_warning

  empty_result:
    - action: expand_time_range_retry
      expand_by: "1 month"
    - action: relax_filters_retry
    - action: return_empty_with_notice

  connection_failed:
    - action: switch_backup_source_retry
    - action: return_cached
    - action: fail
```

#### 3.5.2 恢复流程

```python
class RecoveryAgent:
    async def recover(self, sub_query, error, context) -> RecoveryResult:
        error_type = self._classify_error(error)
        policy_chain = self.policies.get_chain(error_type)

        for policy in policy_chain:
            try:
                result = await self._execute_policy(policy, sub_query, context)
                if result.success:
                    return RecoveryResult(status="recovered", data=result.data, action_taken=policy.action)
            except Exception:
                continue

        return RecoveryResult(status="abandoned", action_taken="none", error=str(error))
```

#### 3.5.3 与 Orchestrator 集成

```python
for sq_id, result in sub_results.items():
    if result.status == "error":
        recovery = await recovery_agent.recover(sub_query, result.error, context)
        if recovery.status == "recovered":
            sub_results[sq_id] = QueryResult(sub_query_id=sq_id, data=recovery.data, status="success")
        elif recovery.is_skipped:
            sub_results[sq_id] = QueryResult(sub_query_id=sq_id, data=[], status="warning")
```

---

### 3.6 Aggregator

**职责**：按意图聚合子查询结果。

```python
class Aggregator:
    _STRATEGIES: dict[str, AggregationStrategy] = {
        "diff": DiffAggregator(),
        "trend_direction": TrendDirectionAggregator(),
        "pearson": PearsonAggregator(),
        "proportion": ProportionAggregator(),
        "ranking": RankingAggregator(),
        "sequential_filter": SequentialFilterAggregator(),
        "hierarchy_expand": HierarchyExpandAggregator(),
    }

    def run(self, results: dict[str, QueryResult], aggregation: str) -> dict:
        strategy = self._STRATEGIES.get(aggregation, PassthroughAggregator())
        return strategy.aggregate(results)
```

**新增聚合策略 = 写一个类注册到 `_STRATEGIES`**。

---

### 3.7 Memory

**职责**：缓存历史 Plan，相似查询直接复用。

```python
class QueryMemory:
    async def get_similar(self, question: str, threshold: float = 0.9) -> Plan | None:
        embedding = await self.embedder.encode(question)
        similar = await self.vector_store.search(embedding, top_k=1)
        if similar and similar[0].score >= threshold:
            return similar[0].plan
        return None

    async def save(self, question: str, plan: Plan, result: AgentResult):
        embedding = await self.embedder.encode(question)
        await self.vector_store.insert(
            embedding=embedding,
            metadata={"question": question, "plan": plan, "status": result.status},
        )
```

---

## 4. Trace 设计（全链路可追溯）

### 4.1 设计原则

- **每个节点记录输入输出**：出了问题能定位"哪个节点、输入了什么、输出了什么"
- **分级记录**：成功时精简，失败时详细
- **树形嵌套**：子查询的 trace 嵌套在外层 trace 中

### 4.2 Trace 结构

```json
{
  "query_id": "uuid",
  "question": "对比华东和华南的销售额",
  "status": "warning",
  "trace": [
    {
      "step": "agent_controller",
      "timestamp": "2026-05-30T10:00:01",
      "input": {"question": "对比华东和华南的销售额"},
      "output": {"routing": "complex", "memory_hit": false}
    },
    {
      "step": "planner",
      "timestamp": "2026-05-30T10:00:02",
      "input": {"question": "...", "entities": ["销售额", "华东", "华南"]},
      "output": {"intent": "compare", "sub_queries_count": 2, "source": "llm"}
    },
    {
      "step": "resolver",
      "timestamp": "2026-05-30T10:00:02",
      "input": {"entities": ["销售额", "华东", "华南"]},
      "output": {"mappings": {"销售额": "sales_amount", "华东": "region=HD", "华南": "region=HN"}}
    },
    {
      "step": "dispatcher",
      "timestamp": "2026-05-30T10:00:03",
      "input": {"sub_queries": [{"id": "sq-1"}, {"id": "sq-2"}]},
      "output": {"parallel_count": 2, "strategy": "parallel"}
    },
    {
      "step": "sub_query_sq-1",
      "timestamp": "2026-05-30T10:00:04",
      "status": "success",
      "trace": [
        {"step": "generate_dsl", "input": {"question": "华东的销售额"}, "output": {"dsl": {...}, "source": "llm"}},
        {"step": "validate_dsl", "input": {"dsl": {...}}, "output": {"valid": true}},
        {"step": "confidence", "input": {"dsl": {...}, "question": "华东的销售额"}, "output": {"confidence": 85, "routing": "continue"}},
        {"step": "build_sql", "input": {"dsl": {...}}, "output": {"sql": "SELECT SUM(order_amount) ... WHERE region_code = 'HD'"}},
        {"step": "execute_sql", "input": {"sql": "..."}, "output": {"rows_returned": 1, "first_row": {"sales_amount": 12000000}}}
      ]
    },
    {
      "step": "sub_query_sq-2",
      "timestamp": "2026-05-30T10:00:05",
      "status": "success",
      "trace": [
        {"step": "generate_dsl", "input": {"question": "华南的销售额"}, "output": {"dsl": {...}, "source": "llm"}},
        {"step": "confidence", "input": {"dsl": {...}, "question": "华南的销售额"}, "output": {"confidence": 70, "routing": "warning"}},
        {"step": "execute_sql", "input": {"sql": "..."}, "output": {"rows_returned": 1, "first_row": {"sales_amount": 9500000}}}
      ]
    },
    {
      "step": "aggregator",
      "timestamp": "2026-05-30T10:00:06",
      "input": {"sub_results": {"sq-1": "success", "sq-2": "success"}, "intent": "compare"},
      "output": {"diff": -2500000, "growth_rate": "-20.83%"}
    }
  ]
}
```

### 4.3 分级记录策略

| 级别 | 记录内容 | 场景 |
|------|---------|------|
| **summary**（默认） | 关键字段 | 正常运行 |
| **detailed**（出错时） | 完整输入输出 | 节点失败 |
| **full**（调试模式） | 全部中间状态 | 开发排查 |

```python
class TraceCollector:
    def add(self, step: str, input=None, output=None, level="summary"):
        record = {"step": step, "timestamp": time.time()}
        if level == "summary":
            record["input"] = self._summarize(input)
            record["output"] = self._summarize(output)
        elif level == "detailed":
            record["input"] = input
            record["output"] = output
        self.steps.append(record)
```

---

## 5. 治理服务化

### 5.1 当前问题

- 启动时加载全部治理配置（metrics/dimensions/permissions）
- 大业务域配置量大，启动慢、内存占用高
- 所有指标在一个 DomainContext 里，RAG 检索范围大、精度低

### 5.2 按需调用设计

```
Agent 提取 entities
  │
  ▼
EntityResolver 查规则表
  │
  ├── "销售额" ──► MetricService("sales_amount")
  ├── "华东"   ──► DimensionService("region")
  └── "orders" ──► DataSourceService("orders")
       │
       ▼
  只实例化这 3 个服务，其余不加载
```

### 5.3 服务接口

```python
class MetricService:
    def get_definition(self, alias: str) -> MetricDefinition
    def validate(self, dsl: DSL) -> ValidationResult
    def resolve_to_sql(self, expr: str) -> str

class DimensionService:
    def get_definition(self, alias: str) -> DimensionDefinition
    def validate_value(self, value: str) -> str  # 返回编码后的值
    def resolve_to_sql(self, column: str, value: str) -> str

class PermissionService:
    def get_row_filters(self, user_id: str) -> list[Filter]
    def get_col_restrictions(self, user_id: str) -> list[str]
    def check_access(self, user_id: str, metric: str) -> bool
```

---

## 6. 与现有系统的兼容

### 6.1 保留的能力

- **LangGraph 管道**：SubQueryAgent 内部仍走现有的 LangGraph 工具链
- **AuditLogger**：trace 格式兼容现有 SQLite 表结构
- **QueryState**：状态字段不变，新增字段 optional
- **SSE 事件**：AgentController 仍 emit SSE 事件，与前端兼容

### 6.2 变更点

| 模块 | 变更 | 影响 |
|------|------|------|
| AgentOrchestrator | 重构为 AgentController + Planner + Dispatcher + RecoveryAgent | 接口不变，内部实现变 |
| Planner | 从关键词匹配升级为 LLM + 配置 | 新增 intents.yaml |
| Aggregator | 从硬编码策略升级为插件注册表 | 新增 aggregation strategies |
| Confidence | 子查询 clarify 降级为 warning | 行为变更 |
| QueryResult | 新增 confidence/explanation 字段 | 兼容旧代码 |

---

## 7. 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| LLM Planner 不稳定 | Plan 格式错误、意图识别错误 | Fallback 到规则规划；严格 JSON schema 校验 |
| LLM 延迟高 | 复杂查询规划耗时 | Memory 缓存；Planner 结果缓存 |
| RecoveryAgent 无限重试 | 死循环 | 每个策略 max_attempts 限制；总重试次数上限 |
| Trace 体积过大 | 存储膨胀 | 分级记录；定期清理旧 trace |
| 治理服务化粒度 | 服务拆分过细导致调用开销 | MVP 阶段进程内调用，后续按需拆进程 |

---

*设计日期：2026-05-30*
*状态：待评审*
