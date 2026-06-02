# Evaluation V2 — Canonical Semantic Benchmark Design

**日期**: 2026-06-02
**版本**: V2.0
**状态**: 设计中

---

## 1. 设计目标

### 1.1 测什么（In Scope）

| 层级 | 测什么 | 为什么 |
|------|--------|--------|
| **Intent** | 用户想查什么（aggregate / rank / time_series / clarification） | NL→DSL 的第一步 |
| **Metric** | 用户要的数值指标是否正确 | 核心语义 |
| **Filter** | 过滤条件是否正确 | 区域=华东、金额>5000 |
| **Dimension** | 分组维度是否正确 | 按品牌、按地区 |
| **Planner** | order_by、limit、join 的规划是否正确 | DSL 结构层面 |
| **Governance** | 权限控制、敏感数据脱敏、审计 | 安全合规 |
| **Ambiguity** | 歧义检测：是否需要澄清 | 用户体验 |
| **Failure** | 错误处理：未知维度、越权查询 | 系统鲁棒性 |

### 1.2 不测什么（Out of Scope）

| 项目 | 原因 |
|------|------|
| SQL 语法正确性 | SQL Builder 的职责 |
| 数据库执行结果 | 集成测试的职责，非语义测试 |
| SQL 方言兼容性 | 换数据库不需要改 benchmark |
| 查询性能 | 性能测试，非语义测试 |
| 前端展示格式 | 前端测试 |

### 1.3 核心结论：A vs B

**答案是 B. Semantic Understanding Benchmark**

理由：
1. 项目定位是 **Semantic Query Engine**，不是 SQL Generator
2. SQL 执行测试不能换数据库，语义测试可以
3. SQL 执行测试依赖数据，语义测试不依赖
4. SQL 执行测试慢（需连接数据库），语义测试快（纯内存比较）
5. SQL 执行测试脆弱（数据变化导致失败），语义测试稳定

SQL 执行测试保留为 V2 的**可选阶段**（`execution` stage）。

---

## 2. Canonical Semantic Resolver

### 2.1 等价边界（属于语义等价）

| 类型 | 示例 A | 示例 B | 等价理由 |
|------|--------|--------|---------|
| **Metric Alias** | `sales_amount` | `pay_amount` | 都映射到 metric_id `sales_amount` |
| **Dimension Alias** | `region` | `region_code` | 都映射到物理列 `region_code` |
| **Value Alias** | `华东` | `HD` | `value_map` 定义了等价关系 |
| **Time Alias** | `2024年` | `["2024-01-01", "2024-12-31"]` | 都映射到同一时间范围 + granularity `year` |
| **Join Entity** | `customer_dim` | `c` | 都映射到业务实体 `customer` |
| **Filter Operator 等价** | `between [a, b]` | `>= a and <= b` | 逻辑等价 |

### 2.2 不等价边界（不属于语义等价）

| 类型 | 示例 A | 示例 B | 不等价理由 |
|------|--------|--------|-----------|
| **不同指标** | `GMV` | `SalesAmount` | metric_id 不同（`gmv` vs `sales_amount`） |
| **不同业务语义** | `Revenue` | `Profit` | 完全不同的业务概念 |
| **不同统计口径** | `Customer Count` | `Active Customer Count` | metric_id 不同 |
| **不同过滤值** | `region = "华东"` | `region = "华南"` | 值不同 |
| **不同时间范围** | `2024年` | `2024年Q1` | 范围不同 |
| **不同聚合函数** | `SUM(pay_amount)` | `AVG(pay_amount)` | 统计方式不同 |

### 2.3 4 项调整

#### 调整 1：Join 比较业务实体

```python
# 不比较表名，比较业务实体
"customer_dim" → entity: "customer"
"c" → entity: "customer"
# 两者等价

"product_dim" → entity: "product"
"p" → entity: "product"
# 两者等价
```

Join 的 canonical 表示：
```json
{
  "entity": "customer",
  "on_field": "customer_id",
  "join_type": "left"
}
```

#### 调整 2：Order By 默认等价规则

```python
# 用户未表达排序意图 → 允许系统默认值
# 用户明确说了"最高的" → 必须 desc
# 用户明确说了"最低的" → 必须 asc
# 用户什么都没说 → 系统默认 desc 算对
```

判定规则：
- expected 有明确 direction → actual 必须匹配
- expected 无 direction（系统默认）→ actual 任意 direction 都算对

#### 调整 3：Metric Canonical 使用 metric_id

```python
# 不直接使用物理表达式作为唯一标识
# 而是通过 metric_id 映射

metrics_config = {
    "sales_amount": {
        "expr": "SUM(pay_amount)",
        "canonical_id": "sales_amount"
    },
    "gmv": {
        "expr": "SUM(order_amount)",
        "canonical_id": "gmv"
    }
}

# DSL: alias="sales_amount", field="pay_amount", func="sum"
# → canonical: "sales_amount"
# DSL: alias="pay_amount", field="pay_amount", func="sum"
# → canonical: "sales_amount"（通过 field+func 反查 metric_id）
```

#### 调整 4：时间语义增加 granularity

```python
class CanonicalTimeRange:
    start: str       # "2024-01-01"
    end: str         # "2024-12-31"
    granularity: str # "day" | "week" | "month" | "quarter" | "year"

# "2024年" → {start: "2024-01-01", end: "2024-12-31", granularity: "year"}
# "2024年1月" → {start: "2024-01-01", end: "2024-01-31", granularity: "month"}
# "最近7天" → {start: "<today-6>", end: "<today>", granularity: "day"}
```

### 2.4 Canonical 化流程

```
原始 DSL
  ↓
[Metric Resolver]    → metric_id（通过 alias 或 field+func 反查）
  ↓
[Dimension Resolver] → 物理列名（通过 dimension_mapping）
  ↓
[Value Resolver]     → 物理值（通过 value_map）
  ↓
[Time Resolver]      → {start, end, granularity}
  ↓
[Join Resolver]      → {entity, on_field, join_type}
  ↓
[Order By Resolver]  → {field, direction | default}
  ↓
Canonical Semantic Representation
```

---

## 3. 目录结构

```
evaluation/
├── __init__.py
├── cli.py                          # CLI 入口
├── config.py                       # 评测配置
│
├── datasets/                       # 测试数据集
│   ├── basic.yaml
│   ├── filter.yaml
│   ├── aggregation.yaml
│   ├── ranking.yaml
│   ├── time.yaml
│   ├── ambiguity.yaml
│   ├── governance.yaml
│   └── failure.yaml
│
├── canonical/                      # Canonical Semantic Resolver
│   ├── __init__.py
│   ├── resolver.py                 # 主解析器
│   ├── metric_resolver.py          # 指标解析
│   ├── dimension_resolver.py       # 维度解析
│   ├── value_resolver.py           # 值解析
│   ├── time_resolver.py            # 时间解析
│   ├── join_resolver.py            # Join 解析
│   └── order_resolver.py           # Order By 解析
│
├── scorers/                        # 评分器
│   ├── __init__.py
│   ├── base.py                     # 抽象基类
│   ├── intent_scorer.py            # 意图评分
│   ├── metric_scorer.py            # 指标评分
│   ├── filter_scorer.py            # 过滤评分
│   ├── planner_scorer.py           # 规划评分（dimension + order_by + limit + join）
│   ├── governance_scorer.py        # 治理评分
│   ├── ambiguity_scorer.py         # 歧义评分
│   └── failure_scorer.py           # 错误评分
│
├── runner/                         # 执行器
│   ├── __init__.py
│   ├── benchmark_runner.py         # 主 runner
│   └── case_loader.py              # 用例加载
│
├── stages/                         # 评测阶段
│   ├── __init__.py
│   ├── semantic_stage.py           # 语义阶段（默认）
│   └── execution_stage.py          # 执行阶段（可选插件）
│
├── reporters/                      # 报告生成
│   ├── __init__.py
│   ├── console_reporter.py         # 控制台报告
│   ├── markdown_reporter.py        # Markdown 报告
│   └── json_reporter.py            # JSON 报告
│
└── models.py                       # 数据模型
```

---

## 4. Benchmark Case Schema

### 4.1 统一格式

```yaml
id: BASIC_001
query: "查询销售额"
difficulty: easy              # easy | medium | hard
category: basic               # basic | filter | aggregation | ranking | time | ambiguity | governance | failure
tags: ["aggregation"]

expected:
  intent: aggregate            # aggregate | rank | time_series | drill_down | clarification
  metric: sales_amount         # metric_id
  dimensions: []               # dimension 列表
  filters: []                  # 过滤条件
  planner:
    order_by: null
    limit: null
    join_required: false
  clarification_required: false
  governance:
    permission: allow          # allow | deny
    sensitive_fields: []
  error: null                  # null | unknown_dimension | unauthorized | ...
```

### 4.2 Filter Case

```yaml
id: FILTER_001
query: "查询华东销售额"
difficulty: easy
category: filter
tags: ["filter", "region"]

expected:
  intent: aggregate
  metric: sales_amount
  filters:
    - field: region
      operator: eq
      value: "华东"
```

### 4.3 Ranking Case

```yaml
id: RANK_001
query: "销售额最高的10个商品"
difficulty: medium
category: ranking
tags: ["ranking", "top_n"]

expected:
  intent: rank
  metric: sales_amount
  dimensions: [product_name]
  planner:
    order_by:
      field: sales_amount
      direction: desc
    limit: 10
```

### 4.4 Ambiguity Case

```yaml
id: AMB_001
query: "查询流水"
difficulty: medium
category: ambiguity
tags: ["ambiguity"]

expected:
  intent: clarification
  clarification_required: true
  # 不指定 metric，因为歧义
```

### 4.5 Governance Case

```yaml
id: GOV_001
query: "查询所有用户手机号"
difficulty: easy
category: governance
tags: ["governance", "sensitive"]

expected:
  intent: aggregate
  metric: customer_count
  governance:
    permission: deny
    sensitive_fields: [customer_phone]
```

### 4.6 Failure Case

```yaml
id: FAIL_001
query: "查询火星销售额"
difficulty: easy
category: failure
tags: ["failure", "unknown"]

expected:
  error: unknown_dimension
```

---

## 5. Scoring Framework

### 5.1 评分原则

- **二元判定**：Canonical 表示一致 = 100 分，不一致 = 0 分
- **无部分分**：不引入 0.8、0.9 等主观分数
- **独立评分**：各维度独立计算，互不影响

### 5.2 评分维度

| 维度 | 评分内容 | 匹配规则 |
|------|---------|---------|
| **Intent** | 意图类型 | `expected.intent == actual.intent` |
| **Metric** | 指标 | `canonical(expected.metric) == canonical(actual.metric)` |
| **Filter** | 过滤条件 | `canonical(expected.filters) == canonical(actual.filters)` |
| **Planner** | 规划（dimension + order_by + limit + join） | 各子维度独立评分，取平均 |
| **Governance** | 治理 | `expected.governance.permission == actual.permission` |

### 5.3 Scorer 接口

```python
from abc import ABC, abstractmethod

class Scorer(ABC):
    @abstractmethod
    def score(self, expected: CanonicalQuery, actual: CanonicalQuery) -> float:
        """Return 1.0 (pass) or 0.0 (fail)."""
        pass
```

---

## 6. 权重设计

### 6.1 默认权重

| 维度 | 权重 | 说明 |
|------|------|------|
| **Intent** | 20% | 用户想查什么 |
| **Metric** | 30% | 核心指标 |
| **Filter** | 20% | 过滤条件 |
| **Planner** | 20% | 规划（dimension + order_by + limit + join） |
| **Governance** | 10% | 安全合规 |

### 6.2 特殊 Case 权重调整

| Case 类型 | 权重调整 | 说明 |
|-----------|---------|------|
| **Ambiguity** | Intent=0%, Metric=0%, Filter=0%, Planner=0%, Governance=0% | 只看 `clarification_required` 是否正确 |
| **Failure** | Intent=0%, Metric=0%, Filter=0%, Planner=0%, Governance=0% | 只看 `error` 类型是否正确 |
| **Governance** | Governance=100% | 其他维度不参与计算 |

### 6.3 Overall Accuracy

```
Overall = Intent×0.20 + Metric×0.30 + Filter×0.20 + Planner×0.20 + Governance×0.10
```

通过阈值判定（默认 0.8）：
- `Overall >= 0.8` → Passed
- `Overall < 0.8` → Failed

---

## 7. Case 分类

### 7.1 V0.1 规模（100 Cases）

| 分类 | 数量 | 说明 |
|------|------|------|
| Basic | 20 | 基础查询（单指标、无过滤） |
| Filter | 20 | 过滤条件（单条件、多条件、复合条件） |
| Aggregation | 15 | 聚合查询（SUM/AVG/COUNT/MIN/MAX） |
| Ranking | 10 | 排序/TopN |
| Time | 15 | 时间范围（年/月/日/最近N天） |
| Ambiguity | 10 | 歧义检测 |
| Governance | 5 | 权限控制 |
| Failure | 5 | 错误处理 |

### 7.2 V0.2 规模（200 Cases）

在 V0.1 基础上增加：
- Join 场景 30 cases
- 复合查询 30 cases
- 多域测试 20 cases
- 边界条件 20 cases

### 7.3 V1.0 规模（500+ Cases）

覆盖全部能力维度 + 多域 + 多语言。

---

## 8. V1 → V2 迁移方案

### 8.1 迁移策略

采用**渐进式迁移**，不一次性替换：

```
Phase 1: 新增 V2 框架（与 V1 并存）
  ├── 创建 evaluation_v2/ 目录
  ├── 实现 Canonical Resolver
  ├── 实现新 Scorer
  └── 编写 V2 数据集

Phase 2: 并行运行
  ├── V1 继续运行（保障现有 CI）
  ├── V2 并行运行（收集数据）
  └── 对比 V1/V2 结果差异

Phase 3: V2 成为主框架
  ├── V2 数据集扩展到 100+ cases
  ├── V1 标记为 deprecated
  └── CI 切换到 V2

Phase 4: V1 清理
  ├── 删除 evaluation/ 旧代码
  ├── V2 重命名为 evaluation/
  └── 文档更新
```

### 8.2 数据迁移

V1 的 `expected_dsl` 可以自动转换为 V2 的 `expected`：

```python
def migrate_v1_to_v2(v1_case: dict) -> dict:
    """将 V1 的 expected_dsl 转换为 V2 的 expected。"""
    v1_dsl = v1_case["expected_dsl"]
    return {
        "intent": infer_intent(v1_dsl),
        "metric": extract_metric_id(v1_dsl),
        "dimensions": v1_dsl.get("dimensions", []),
        "filters": canonicalize_filters(v1_dsl.get("filters", [])),
        "planner": {
            "order_by": v1_dsl.get("order_by"),
            "limit": v1_dsl.get("limit"),
            "join_required": bool(v1_dsl.get("joins")),
        },
    }
```

### 8.3 兼容性

- V2 的 `expected` 不存储完整 DSL，只存储语义预期
- V2 的 Runner 调用 API 获取 actual DSL，然后 Canonical 化比较
- V1 的 SQL 执行测试作为 V2 的 `execution_stage` 插件保留

---

## 9. 实施计划

### Phase 1: 核心框架（1-2 周）

| 任务 | 说明 |
|------|------|
| 1.1 Canonical Resolver | 实现 metric/dimension/value/time/join/order resolver |
| 1.2 Scorer 基类 + 5 个 scorer | intent/metric/filter/planner/governance |
| 1.3 Case Loader | YAML 加载 + 校验 |
| 1.4 Benchmark Runner | 主执行器，支持 stage 选择 |
| 1.5 Reporter | Console + Markdown + JSON |

### Phase 2: 数据集（1-2 周）

| 任务 | 说明 |
|------|------|
| 2.1 编写 V0.1 数据集 | 100 cases，覆盖 8 个分类 |
| 2.2 数据集验证 | 确保每个 case 的 expected 可解析 |
| 2.3 基线测试 | 运行 V2 评测，记录当前系统得分 |

### Phase 3: 集成与迁移（1 周）

| 任务 | 说明 |
|------|------|
| 3.1 CLI 集成 | `python -m evaluation run --stage semantic` |
| 3.2 CI 配置 | GitHub Actions 运行 V2 评测 |
| 3.3 V1 并存 | V1 保留，V2 作为新命令 |
| 3.4 文档更新 | README + 使用指南 |

### Phase 4: 扩展（持续）

| 任务 | 说明 |
|------|------|
| 4.1 数据集扩展 | V0.2 → V1.0 |
| 4.2 Execution Stage | 集成 SQL 执行测试 |
| 4.3 性能测试 | 评测执行速度 |
| 4.4 回归测试 | 每次发布前运行全量 benchmark |

---

## 10. 关键设计决策

### 10.1 为什么不用 DSL 完全相等

DSL 完全相等非常脆弱：
- alias 名不同（`sales_amount` vs `pay_amount`）→ 语义相同但 DSL 不同
- filter 写法不同（`between` vs `>= and <=`）→ 语义相同但结构不同
- join 顺序不同 → 语义相同但 DSL 不同

Canonical Semantic 消除了这些表面差异。

### 10.2 为什么二元评分（100/0）

部分分（0.8、0.9）主观性太强：
- "alias 对了但 field 错了" → 0.8？这取决于 alias 和 field 哪个更重要
- "两个 filter 中有一个对了" → 0.5？这取决于 filter 之间的权重

Canonical 化后，要么等价（100），要么不等价（0），判定标准客观。

### 10.3 为什么 V1 的 SQL 执行测试保留为插件

虽然 V2 不测 SQL，但 SQL 执行测试仍有价值：
- 验证 DSL→SQL 转换的正确性
- 验证 SQL 语法是否正确
- 验证查询结果是否符合预期

作为可选插件，开发者在需要时启用，不影响日常语义测试的速度。

---

## 附录 A：Canonical 表示示例

### 示例 1：基础查询

```yaml
# Case
query: "查询华东销售额"
expected:
  intent: aggregate
  metric: sales_amount
  filters:
    - field: region
      operator: eq
      value: "华东"
```

```json
// 系统返回 DSL
{
  "metrics": [{"func": "sum", "field": "pay_amount", "alias": "pay_amount"}],
  "filters": [{"field": "region_code", "operator": "=", "value": "HD"}]
}

// Canonical 化后
{
  "intent": "aggregate",
  "metric": "sales_amount",
  "filters": ["region_code = HD"]
}

// expected Canonical 化后
{
  "intent": "aggregate",
  "metric": "sales_amount",
  "filters": ["region_code = HD"]  // "华东" → "HD" via value_map
}

// 结果：匹配 → 100 分
```

### 示例 2：歧义检测

```yaml
# Case
query: "查询流水"
expected:
  intent: clarification
  clarification_required: true
```

```json
// 系统返回 DSL（错误：没有检测到歧义）
{
  "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}]
}

// Canonical 化后
{
  "intent": "aggregate",  // 不是 "clarification"
  "metric": "sales_amount"
}

// expected Canonical 化后
{
  "intent": "clarification",
  "clarification_required": true
}

// 结果：Intent 不匹配 → 0 分
// Ambiguity Scorer 单独判定：clarification_required=false ≠ true → 0 分
```

### 示例 3：时间查询

```yaml
# Case
query: "2024年的销售额"
expected:
  intent: aggregate
  metric: sales_amount
  time:
    start: "2024-01-01"
    end: "2024-12-31"
    granularity: "year"
```

```json
// 系统返回 DSL
{
  "time_field": "order_date",
  "time_range": ["2024-01-01", "2024-12-31"]
}

// Canonical 化后（通过 TimeResolver）
{
  "intent": "aggregate",
  "metric": "sales_amount",
  "time": {
    "start": "2024-01-01",
    "end": "2024-12-31",
    "granularity": "year"
  }
}

// 结果：匹配 → 100 分
```
