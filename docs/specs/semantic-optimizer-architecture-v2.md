# Semantic Query Optimizer V1 — 架构详细设计

> 基于 Error Taxonomy v2 的规则引擎架构详细设计。

---

## 1. 架构总览

```
                          Raw DSL
                             │
                             ▼
                    ┌─────────────────┐
                    │   Normalizer    │  ← 规范化（不依赖语义层配置）
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  Rule Engine    │  ← 规则检测 + 修正（依赖 SemanticConfig）
                    │  ┌───────────┐  │
                    │  │Dispatcher │  │
                    │  │  ┌──────┐ │  │
                    │  │  │Queue │ │  │
                    │  │  └──┬───┘ │  │
                    │  │     ▼     │  │
                    │  │  Pipeline│  │
                    │  │  ┌──────┐│  │
                    │  │  │Groups││  │
                    │  │  └──────┘│  │
                    │  └───────────┘  │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │CanonicalResolver│  ← 终态规范化（与 Benchmark 共享资产）
                    └────────┬────────┘
                             │
                             ▼
                    (OptimizedDSL, OptimizationReport)
```

**三层处理**：

| 层 | 职责 | 输入 | 输出 | 与谁共享 |
|----|------|------|------|---------|
| **Normalizer** | 结构级规范化（不依赖语义层配置） | Raw DSL (dict/Pydantic) | Normalized DSL | 无 |
| **Rule Engine** | 语义检测与修正（依赖 SemanticConfig） | Normalized DSL + Context | Partially-Optimized DSL + Report | 无 |
| **Canonical Resolver** | 终态规范化（指标展开、维度解析、值映射） | Optimized DSL | Canonical DSL | Benchmark (evaluation) |

> **解耦理由**：Normalizer 和 Rule Engine 不依赖 CanonicalResolver。Optimizer 和 Benchmark 只在 Canonical Resolver 一层共享资产。避免 Optimizer 的修改影响 Benchmark 的评分逻辑。

---

## 2. 管道中的位置（最终版）

```
generate_dsl
    │
    ▼
validate_dsl              ← 结构正确性（Schema 校验、字段白名单、操作符白名单）
    │
    ▼
RuleOptimizer             ← 语义质量（始终执行）
    │
    ├── Normalizer
    ├── Rule Engine
    └── Canonical Resolver
    │
    ▼
permission_check          ← 权限注入
    │
    ▼
  (continue pipeline...)
```

**关键规则**：
- `validate_dsl` 负责**结构正确性**（有没有语法错误？字段是否存在？）
- `RuleOptimizer` 负责**语义质量**（语义是否合理？指标用对了吗？有没有歧义？）
- RuleOptimizer **始终执行**，不依赖 validate_dsl 的结果
- 如果 validate_dsl 失败但 RuleOptimizer 能修正 → 修正后 re_validate 再继续
- 如果 RuleOptimizer 遇到 Fatal Reject → 流程终止，返回错误报告

---

## 3. Normalizer

### 3.1 职责

将 Raw DSL（LLM 输出的 dict 或 Pydantic 对象）规范化为标准结构，**不依赖语义层配置**。

### 3.2 规范化的内容

| 操作 | 说明 | 示例 |
|------|------|------|
| **字段标准化** | 确保所有可选字段存在，缺失的设为默认值 | `limit` 缺失 → 注入 `100` |
| **类型强制** | 确保字段类型正确 | `limit: "10"` → `limit: 10` |
| **结构展平** | 接受多种 filter 表示形式，统一为标准格式 | `filters: {"op": "and", ...}` 或 `filters: [...]` → 统一为 list[Filter] |
| **别名补充** | 为无 alias 的 metric 生成默认 alias | `SUM(pay_amount)` → `SUM(pay_amount) AS pay_amount` |
| **空白清理** | 维度/指标去重、空列表处理 | `dimensions: ["a", "a"]` → `["a"]` |

### 3.3 不做的事

- ❌ 不查语义层配置（不判断 metric 是否注册）
- ❌ 不访问权限配置（不判断字段是否敏感）
- ❌ 不做值映射（不将"男性"转为 1）

### 3.4 接口

```python
class Normalizer:
    """结构级规范化器。无外部依赖。"""

    def normalize(self, raw_dsl: dict) -> NormalizedDSL:
        """返回规范化后的 DSL + 规范化日志。"""
        ...
```

---

## 4. Rule Engine

### 4.1 RuleMetadata Schema

每条规则注册时携带以下元数据：

```python
@dataclass
class RuleMetadata:
    """规则的注册元数据。"""

    # --- Identity ---
    error_code: str              # e.g. "M001"
    category: str                # "Metric" | "Dimension" | "Filter" | "Intent"
                                 #   | "Planning" | "Time" | "Ambiguity" | "Governance" | "Structural"
    description: str             # 人类可读的一句话描述

    # --- Scheduling ---
    priority: int                # 1-6 (P1 Block → P6 Ambiguity)
    enabled: bool = True         # 是否启用（支持 A/B 测试）

    # --- Behavior ---
    auto_fixable: bool           # True → 规则可自动修正; False → 仅检测
    severity: str                # "Fix" | "Warn" | "Reject"
    confidence: str              # "high" | "medium" | "low"
    is_fatal: bool = False       # True → Fatal Reject（立即终止管道）
                                 # False → Normal Reject（继续收集其他错误）

    # --- Benchmark ---
    benchmark_weight: float = 0.0  # 在 Evaluation 中的权重（与 Eval 权重对齐）
```

### 4.2 Rule Interface

```python
class BaseRule(ABC):
    """规则的抽象基类。"""

    metadata: ClassVar[RuleMetadata]

    @abstractmethod
    def check(self, dsl: NormalizedDSL, context: RuleContext) -> RuleResult:
        """检测语义问题。"""
        ...

    def fix(self, dsl: NormalizedDSL, result: RuleResult) -> NormalizedDSL:
        """应用修正。默认实现直接应用 result.after。"""
        ...
```

### 4.3 RuleContext

```python
@dataclass
class RuleContext:
    """规则执行所需的只读上下文。"""

    # 语义层配置（从 metrics.yaml / dimensions.yaml 加载）
    semantic_config: SemanticConfig

    # 用户信息
    user_id: str | None = None
    user_role: str | None = None       # e.g. "analyst", "manager"

    # 权限配置（从 permissions.yaml 加载）
    permission_config: PermissionConfig | None = None

    # 原始用户问题（用于歧义检测 A001/A002、时间语义 T001/T002）
    original_question: str | None = None
```

### 4.4 RuleResult

```python
@dataclass
class RuleResult:
    """单条规则的执行结果。"""

    # --- 标识 ---
    error_code: str              # e.g. "M001"
    category: str
    severity: str                # "Fix" | "Warn" | "Reject"
    confidence: str              # "high" | "medium" | "low"
    is_fatal: bool = False

    # --- 内容 ---
    description: str             # 人类可读描述
    before: Any | None = None    # 优化前状态
    after: Any | None = None     # 优化后状态（Reject 时为 None）
    location: str | None = None  # DSL 中的位置 e.g. "metrics[0].func"

    # --- 澄清（A001/A002/T002） ---
    clarification_required: bool = False
    clarification_question: str | None = None
    candidate_values: list[str] = field(default_factory=list)

    # --- 元数据 ---
    applied: bool = False        # Fix 是否已被应用
```

---

## 5. Priority Queue & Pipeline

### 5.1 Priority 定义

```
P1 — Block:       结构完整性检查。S001, S002, I001
                  失败 → Fatal Reject，立即终止

P2 — Identity:    确定性修正。M001, M003, D003, F002
                  不依赖其他规则的结果
                  全部 Fix，失败 → Normal Reject

P3 — Consistency: 跨组件一致性。M004, I002, D002, F001
                  依赖 P2 修正后的 DSL 状态
                  有 Fix / Warn / Reject

P4 — Auth:        权限检查。G001, G002
                  必须先完成 P2/P3 的规范化（确定最终的 metric/dimension 集合）
                  Fatal Reject → 立即终止

P5 — Completeness: 补全与警告。F003, F004, F005, P001-P004, T001-T002
                   依赖 P2/P3 修正后的完整 DSL 状态
                   主要是 Warn + 少数 Fix

P6 — Ambiguity:   歧义检测。A001, A002
                  最后执行，此时所有确定性修正已完成
                  Reject + clarification_required
```

### 5.2 优先级设计理由

```
为什么 Auth 在 Consistency 之后？

  因为 P2/P3 会修正 metric 和 dimension。
  G002 需要知道"最终要访问哪些指标"才能判断权限。
  如果先执行 Auth，可能因为 LLM 的拼写错误而误判权限。
  先修正确定性问题，再判断权限 → 减少误报。

为什么 Ambiguity 在最后？

  因为 P2/P3/P5 的规则可能修正或消除部分歧义。
  例如：P5 的 F001 将"华东区"修正为"华东"后，
  A002 对 region 维度的歧义可能自然消除。
```

### 5.3 执行流程

```
Rule Dispatcher
    │
    ├─ Phase 1: Schedule
    │     └─ 从 RuleRegistry 加载所有 enabled=True 的规则
    │        按 priority 分组 → PriorityQueue
    │
    ├─ Phase 2: Execute (P1 → P6 顺序)
    │     └─ For each priority_level:
    │          ├─ Parallel: 执行该 Level 内所有规则的 .check()
    │          ├─ Collect: 收集 RuleResult[]
    │          ├─ Apply Fixes: 对 severity="Fix" 的结果调用 .fix()
    │          ├─ Fatal Check:
    │          │   ├─ 任何 Fatal Reject → 立即返回 OptimizationReport
    │          │   └─ 否则 → 继续下一 Priority
    │          └─ Update DSL: 将 Fix 后的 DSL 传给下一 Priority
    │
    └─ Phase 3: Compose Report
         └─ 汇总所有 RuleResult → OptimizationReport
```

### 5.4 Reject 分级

| Reject 类型 | 行为 | 使用场景 |
|------------|------|---------|
| **Fatal Reject** (`is_fatal=True`) | 立即终止管道，不再执行后续 Priority | S001, S002, I001, G001, G002 |
| **Normal Reject** (`is_fatal=False`) | 记录错误，继续执行后续 Priority 收集更多问题 | M004, I002, D002, F004, T002, A001, A002 |

> **设计意图**：Normal Reject 的目标是一次返回尽可能完整的问题列表，而不是发现一个错误就停止。

---

## 6. Rule Registry

### 6.1 设计

Rule Registry 是所有规则的**注册中心**。它不执行规则逻辑，只负责：
- 加载规则（从代码注册或配置文件）
- 按 priority / category / enabled 过滤规则
- 提供查询接口

```python
class RuleRegistry:
    """规则注册中心。"""

    _rules: dict[str, type[BaseRule]] = {}

    @classmethod
    def register(cls, rule_class: type[BaseRule]) -> type[BaseRule]:
        """装饰器：注册规则。"""
        metadata = rule_class.metadata
        cls._rules[metadata.error_code] = rule_class
        return rule_class

    @classmethod
    def get_all(cls, enabled_only: bool = True) -> list[type[BaseRule]]:
        """获取所有规则。"""
        ...

    @classmethod
    def get_by_priority(cls, priority: int, enabled_only: bool = True) -> list[type[BaseRule]]:
        """按优先级获取规则。"""
        ...

    @classmethod
    def get_by_category(cls, category: str) -> list[type[BaseRule]]:
        """按类别获取规则。"""
        ...

    @classmethod
    def build_queue(cls, enabled_only: bool = True) -> PriorityQueue:
        """构建优先级队列（P1→P6，每组内部规则任意顺序）。"""
        ...
```

### 6.2 使用方式

```python
# 装饰器注册
@RuleRegistry.register
class FixWrongAggFunc(BaseRule):
    metadata = RuleMetadata(
        error_code="M001",
        category="Metric",
        description="Wrong aggregation function for registered metric",
        priority=2,      # P2 Identity
        enabled=True,
        auto_fixable=True,
        severity="Fix",
        confidence="high",
        is_fatal=False,
        benchmark_weight=0.20,
    )

    def check(self, dsl, context):
        ...
```

---

## 7. Rule Group 详细职责

### 7.1 Metric Group (`M001-M004`)

| 规则 | Priority | check() 逻辑 | fix() 逻辑 | auto_fixable |
|------|----------|-------------|-----------|-------------|
| **M001** Wrong AggFunc | P2 | 遍历 metrics，比对 `func` 与语义层定义的 `expr` 中的 func；不一致则触发 | 替换 `func` 为语义层定义 | ✅ |
| **M002** Unregistered Metric | P5 | 遍历 metrics，检查 field 是否在语义层注册；找不到则触发 | — | ❌ (Warn only) |
| **M003** Missing Alias | P2 | 遍历 metrics，检查 alias 是否为空 | 生成 `{func}_{field}` 格式的 alias | ✅ |
| **M004** Metric-DataSource Mismatch | P3 | 检查 metric 的注册 data_sources 是否包含当前 DSL 的 data_source | — | ❌ (Reject) |

### 7.2 Dimension Group (`D001-D003`)

| 规则 | Priority | check() 逻辑 | fix() 逻辑 | auto_fixable |
|------|----------|-------------|-----------|-------------|
| **D001** Unregistered Dimension | P5 | 遍历 dimensions，检查是否在语义层注册 | — | ❌ (Warn only) |
| **D002** Dimension Not In DataSource | P3 | 检查 dimension 是否属于当前 data_source 或可 JOIN 到达 | — | ❌ (Reject) |
| **D003** Redundant Dimension | P2 | 检查 dimensions 列表是否有重复 | 去重（保留首次出现） | ✅ |

### 7.3 Filter Group (`F001-F005`)

| 规则 | Priority | check() 逻辑 | fix() 逻辑 | auto_fixable |
|------|----------|-------------|-----------|-------------|
| **F001** Invalid Enum Value | P3 | 对每个 filter，检查 field 是否有 value_map；如有，检查 value 是否在 map 中 | 编辑距离 ≤ 1 → 替换；编辑距离 ≤ 2 → 替换 + medium confidence | ✅ (high/medium) |
| **F002** Operator-Type Mismatch | P2 | 对每个 filter，检查 operator 与字段类型是否兼容 | `LIKE` on INTEGER → `=`; `>` on BOOLEAN → `=` | ✅ |
| **F003** Missing Time Range | P5 | 检查 original_question 是否包含时间关键词，同时 DSL 缺少 time_range/filters 中的时间条件 | — | ❌ (Warn only) |
| **F004** Contradictory Filters | P5 | 检查同一 field 是否出现在多个 filter 中且值互斥（AND 语义下） | — | ❌ (Reject) |
| **F005** Value Type Mismatch | P5 | 检查 filter value 的类型是否与字段类型匹配 | — | ❌ (Warn only) |

### 7.4 Intent Group (`I001-I002`)

| 规则 | Priority | check() 逻辑 | fix() 逻辑 | auto_fixable |
|------|----------|-------------|-----------|-------------|
| **I001** Unknown DataSource | P1 | 检查 data_source 是否在 semantic_config.data_sources 中 | — | ❌ (Fatal Reject) |
| **I002** DataSource-Only Metric | P3 | 如果 data_source 中没有当前 metrics 的任何一个，查找正确的 data_source | 唯一匹配 → Fix data_source; 多匹配 → Reject | ✅ (唯一时) |

### 7.5 Planning Group (`P001-P004`)

| 规则 | Priority | check() 逻辑 | fix() 逻辑 | auto_fixable |
|------|----------|-------------|-----------|-------------|
| **P001** Missing Required JOIN | P5 | 检查 metrics 和 dimensions 涉及的所有表；如果 >1 个表且 DSL 缺少 JOIN | JOIN 路径唯一 → Fix (注入); 多路径 → Warn | ✅ (唯一路径) |
| **P002** Unnecessary JOIN | P5 | 检查 DSL 中的 JOIN 表是否被任何 metric/dimension 实际引用 | — | ❌ (Warn only) |
| **P003** Limit Exceeds Max | P5 | 检查 limit > NL2DSL_MAX_LIMIT | 截断为 MAX_LIMIT | ✅ |
| **P004** OrderBy Not In Output | P5 | 检查 order_by 的 field 是否在 metrics alias 或 dimensions 中 | — | ❌ (Warn only) |

### 7.6 Time Group (`T001-T002`)

| 规则 | Priority | check() 逻辑 | fix() 逻辑 | auto_fixable |
|------|----------|-------------|-----------|-------------|
| **T001** Invalid Time Grain | P5 | 检查 metric 命名中的粒度词（daily/monthly）与 dimensions 中的时间维度粒度是否一致 | — | ❌ (Warn only) |
| **T002** Missing Time Context | P5 | 检查 original_question 中的对比关键词（同比/环比/去年同期），检查 DSL 中是否有 comparison 信息 | — | ❌ (Reject + Clarify) |

### 7.7 Ambiguity Group (`A001-A002`)

| 规则 | Priority | check() 逻辑 | fix() 逻辑 | auto_fixable |
|------|----------|-------------|-----------|-------------|
| **A001** Ambiguous Metric | P6 | 对每个 metric 的 field，在语义层做模糊匹配；如果 ≥2 个候选 → 歧义 | — | ❌ (Reject + Clarify) |
| **A002** Ambiguous Dimension | P6 | 对每个 dimension，在语义层做模糊匹配；如果 ≥2 个候选 → 歧义 | — | ❌ (Reject + Clarify) |

### 7.8 Governance Group (`G001-G002`)

| 规则 | Priority | check() 逻辑 | fix() 逻辑 | auto_fixable |
|------|----------|-------------|-----------|-------------|
| **G001** Sensitive Field Access | P4 | 遍历 DSL 涉及的所有字段，检查是否在 permission_config.sensitive_fields 中，且未配置脱敏规则 | — | ❌ (Fatal Reject) |
| **G002** Metric Not Authorized | P4 | 检查 user_role 是否在权限配置中拥有所有请求 metrics 的访问权 | — | ❌ (Fatal Reject) |

### 7.9 Structural Group (`S001-S002`)

| 规则 | Priority | check() 逻辑 | fix() 逻辑 | auto_fixable |
|------|----------|-------------|-----------|-------------|
| **S001** Empty Query | P1 | 检查 metrics 和 dimensions 是否同时为空 | — | ❌ (Fatal Reject) |
| **S002** Missing DataSource | P1 | 检查 data_source 是否存在且非空 | — | ❌ (Fatal Reject) |

---

## 8. OptimizationReport

### 8.1 Schema

```python
@dataclass
class OptimizationReport:
    """一次优化运行的完整报告。"""

    # --- 标识 ---
    report_id: str                    # UUID
    query_id: str | None = None      # 关联的查询 ID

    # --- 统计 ---
    total_rules_checked: int = 0
    total_rules_triggered: int = 0

    fixes_applied: list[RuleResult] = field(default_factory=list)
    fixes_bypassed: list[RuleResult] = field(default_factory=list)  # 触发但 confidence 太低未应用
    warnings_issued: list[RuleResult] = field(default_factory=list)
    rejections: list[RuleResult] = field(default_factory=list)      # Normal Reject
    fatal_rejection: RuleResult | None = None                        # Fatal Reject

    # --- 指标 ---
    fix_rate: float = 0.0             # fixes / total_triggered
    warning_rate: float = 0.0         # warnings / total_triggered
    rejection_rate: float = 0.0       # rejections / total_triggered
    fatal: bool = False               # 是否被 Fatal Reject 终止

    # --- 性能 ---
    elapsed_ms: int = 0
    phases: dict[str, int] = field(default_factory=dict)  # phase_name → ms

    # --- DSL 对照 ---
    dsl_before: dict | None = None
    dsl_after: dict | None = None
    diff: list[str] = field(default_factory=list)  # 人类可读的变更列表
```

### 8.2 示例输出

```json
{
  "report_id": "opt_abc123",
  "query_id": "q_xyz789",
  "total_rules_checked": 26,
  "total_rules_triggered": 4,
  "fixes_applied": [
    {
      "error_code": "M001",
      "severity": "Fix",
      "confidence": "high",
      "description": "Aggregation function corrected: AVG → SUM for metric 'sales_amount'",
      "before": {"func": "avg", "field": "order_amount"},
      "after": {"func": "sum", "field": "pay_amount"}
    },
    {
      "error_code": "F001",
      "severity": "Fix",
      "confidence": "medium",
      "description": "Enum value corrected: '华东区' → '华东' (edit distance=1)",
      "before": {"field": "region", "value": "华东区"},
      "after": {"field": "region", "value": "华东"}
    }
  ],
  "warnings_issued": [
    {
      "error_code": "F003",
      "severity": "Warn",
      "confidence": "medium",
      "description": "Query contains time keyword '本月' but DSL has no time_range filter"
    }
  ],
  "rejections": [],
  "fatal_rejection": null,
  "fix_rate": 0.50,
  "warning_rate": 0.25,
  "rejection_rate": 0.0,
  "fatal": false,
  "elapsed_ms": 12,
  "diff": [
    "metrics[0].func: avg → sum",
    "metrics[0].field: order_amount → pay_amount",
    "filters[0].value: 华东区 → 华东"
  ]
}
```

---

## 9. 与 Evaluation Framework 的集成

### 9.1 集成方式

Optimizer 的收益通过 Evaluation Framework **前后对比**来量化：

```
Before:   NL → generate_dsl → validate_dsl → [直接进入后续管道]
After:    NL → generate_dsl → validate_dsl → RuleOptimizer → [后续管道]

对比指标：Evaluation 的 4 大类 12 维度得分变化
```

### 9.2 新增 Evaluation 维度

在现有的 12 维度基础上，建议新增一个 **Optimization 类别**：

| 维度 | 权重 | 说明 | 评分逻辑 |
|------|------|------|---------|
| **Rule Fix Rate** | 5% | RuleOptimizer 触发的规则中，成功自动修正的比例 | `fixes_applied / total_triggered` |
| **Rule Coverage** | 3% | 26 条规则中，被触发的比例（反映测试集对规则的覆盖度） | `distinct_error_codes / 26` |
| **Optimization Gain** | 5% | 优化前后的 Overall Score 差值 | `score_after - score_before`，clip 到 [0, 1] |

> **注意**：Optimization Gain 是最直接的价值指标。如果 Gain ≈ 0，说明 Optimizer 没有带来实际收益，需要检查规则是否有效或测试集是否足够。

### 9.3 Benchmark 运行流程

```
1. 加载测试数据集 (tests/evaluation/dataset/)
2. 对每个用例：
   a. 运行 Baseline（Optimizer OFF）
      → 记录 scores_baseline
   b. 运行 With Optimizer（Optimizer ON）
      → 记录 scores_optimized
   c. 计算 delta = scores_optimized - scores_baseline
   d. 收集 OptimizationReport
3. 聚合：
   a. 整体得分变化（按 Category / Dimension）
   b. Rule Fix Rate（每条规则被触发和修正的次数）
   c. Per Error Code 统计（哪些错误最常见）
   d. False Positive 分析（哪些 Fix 导致得分下降）
4. 生成对比报告
```

### 9.4 CLI 扩展

```bash
# 运行带 Optimizer 的基准测试
nl2dsl-eval --dataset tests/evaluation/dataset --optimizer on --output reports/

# 对比模式：Optimizer ON vs OFF
nl2dsl-eval --dataset tests/evaluation/dataset --compare --output reports/

# 仅运行特定规则
nl2dsl-eval --dataset tests/evaluation/dataset --rules M001,M002,F001

# 禁用特定规则
nl2dsl-eval --dataset tests/evaluation/dataset --disable-rules A001,A002

# 输出优化详情（每个用例的 OptimizationReport）
nl2dsl-eval --dataset tests/evaluation/dataset --optimizer on --verbose-optimizer
```

### 9.5 报告示例

```
# NL2DSL Evaluation Report — With Semantic Optimizer

## Overall Score: 89.1% (+6.8% vs Baseline 82.3%)

## By Category
| Category     | Weight | Baseline | Optimized | Delta  |
| Semantic     | 56%    | 88.5%    | 94.2%     | +5.7%  |
| Planning     | 14%    | 75.0%    | 82.1%     | +7.1%  |
| Execution    | 20%    | 90.0%    | 90.0%     | 0.0%   |
| Governance   | 10%    | 65.0%    | 85.0%     | +20.0% |
| Optimization | 13%    | —        | 91.5%     | NEW    |

## Optimizer Stats
| Metric              | Value |
| Rules Checked       | 26    |
| Rules Triggered     | 8.3 avg/case |
| Fixes Applied       | 5.1 avg/case |
| Fix Rate            | 61.4% |
| Warnings Issued     | 2.1 avg/case |
| Rejections          | 1.1 avg/case |
| Avg Latency         | 11.2 ms |

## Top Fixed Errors
| Error Code | Count | Description                    |
| M001        | 12    | Wrong aggregation function     |
| F001        | 8     | Invalid enum value             |
| P003        | 6     | Limit exceeds max              |
| M003        | 5     | Missing alias                  |

## Optimization Gain Breakdown (by Dimension)
| Dimension    | Baseline | Optimized | Gain  |
| Metric       | 85%      | 95%       | +10%  |
| Filter       | 82%      | 91%       | +9%   |
| Permission   | 80%      | 100%      | +20%  |
| Limit        | 60%      | 85%       | +25%  |
```

---

## 10. 文件结构规划

```
nl2dsl/optimizer/
├── __init__.py              # 公开 API
├── normalizer.py            # Normalizer（结构级规范化）
├── engine.py                # RuleEngine 入口 + Dispatcher + Pipeline
├── registry.py              # RuleRegistry（规则注册中心）
├── context.py               # RuleContext
├── report.py                # OptimizationReport
├── metadata.py              # RuleMetadata
├── base.py                  # BaseRule + RuleResult
├── rules/
│   ├── __init__.py          # 导出所有规则
│   ├── metric.py            # M001-M004
│   ├── dimension.py         # D001-D003
│   ├── filter.py            # F001-F005
│   ├── intent.py            # I001-I002
│   ├── planning.py          # P001-P004
│   ├── time.py              # T001-T002
│   ├── ambiguity.py         # A001-A002
│   ├── governance.py        # G001-G002
│   └── structural.py        # S001-S002
└── tests/
    ├── __init__.py
    ├── test_normalizer.py
    ├── test_metric_rules.py
    ├── test_filter_rules.py
    ├── test_governance_rules.py
    └── ...
```

---

## 11. 设计决策汇总

| # | 决策 | 理由 |
|---|------|------|
| 1 | Optimizer 始终执行（不在 validate 失败时才触发） | validate 管结构，Optimizer 管语义 — 正交职责 |
| 2 | Normalizer → Rule Engine → Canonical Resolver 三层解耦 | 避免 Optimizer 与 Benchmark 的 CanonicalResolver 强耦合 |
| 3 | P1 Block → P2 Identity → P3 Consistency → P4 Auth → P5 Completeness → P6 Ambiguity | 先规范化为正确形式，再做权限判断；歧义检测最后执行 |
| 4 | Fatal Reject vs Normal Reject 分级 | Normal Reject 继续收集错误 → 一次返回完整问题列表 |
| 5 | RuleMetadata 支持 enabled / auto_fixable / benchmark_weight | 支持 A/B 测试、动态启停、Evaluation 权重对齐 |
| 6 | OptimizationReport 独立于 EvaluationReport | 两者关注不同：OptimizationReport 是过程指标，EvaluationReport 是结果指标 |
| 7 | 复用 Canonical Resolver 而非替换 | V1 不重复造轮子，与 Benchmark 共享语义规范化资产 |
