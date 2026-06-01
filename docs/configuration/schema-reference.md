# 配置 Schema 参考

所有业务配置通过 YAML 文件定义，放置于 `configs/` 目录。系统启动时自动加载并同步到向量库。

---

## metrics.yaml

定义**指标**、**维度**和**数据源**。

```yaml
metrics:
  sales_amount:
    expr: "SUM(pay_amount)"
    description: "销售额"
    data_source: orders

dimensions:
  region:
    column: region_code
    description: "地区"
    value_map:
      HD: "华东"
      HN: "华南"
      HB: "华北"

data_sources:
  orders:
    table: orders
    metrics: [sales_amount, order_count]
    dimensions: [region, category, order_date]
```

### metrics 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `expr` | string | ✅ | SQL 表达式，如 `SUM(pay_amount)` |
| `description` | string | ✅ | 指标中文名，用于 RAG 检索 |
| `data_source` | string | ✅ | 所属数据源标识 |

### dimensions 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `column` | string | ✅ | 数据库实际字段名 |
| `description` | string | ✅ | 维度中文名 |
| `value_map` | dict | ❌ | 编码→中文映射，如 `HD: 华东` |

### data_sources 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `table` | string | ✅ | 数据库表名 |
| `metrics` | list | ✅ | 该表支持的指标列表 |
| `dimensions` | list | ✅ | 该表支持的维度列表 |

---

## terms.yaml

定义**业务术语**和**别名映射**，提升语义理解准确性。

```yaml
terms:
  销售额:
    aliases: ["营收", "收入", "GMV"]
    metric: sales_amount

  华东:
    aliases: ["东部地区", "江浙沪"]
    dimension: region
    value: "HD"
```

### terms 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `aliases` | list | ✅ | 口语化别名列表 |
| `metric` | string | ❌ | 映射到的指标标识（与 dimension 二选一）|
| `dimension` | string | ❌ | 映射到的维度标识 |
| `value` | string | ❌ | 维度值编码（仅当 dimension 存在时）|

---

## intents.yaml

定义**查询意图**，控制复杂查询的分解和聚合策略。

```yaml
intents:
  compare:
    keywords: ["对比", "比较", "同比", "环比"]
    decomposition: split_by_objects
    aggregation: diff
    description: "对比分析"

  trend:
    keywords: ["趋势", "走势", "增长", "下降"]
    decomposition: single_with_time_grouping
    aggregation: trend_direction
    description: "趋势分析"

  single_query:
    keywords: []
    decomposition: none
    aggregation: none
    description: "单查询（默认兜底）"
```

### intents 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `keywords` | list | ✅ | 触发该意图的关键词（为空表示兜底）|
| `decomposition` | string | ✅ | 分解策略：`none` / `split_by_objects` / `single_with_time_grouping` / `total_plus_groups` |
| `aggregation` | string | ✅ | 聚合策略：`none` / `diff` / `trend_direction` / `pearson` / `proportion` / `ranking` |
| `description` | string | ✅ | 意图描述 |

---

## permissions.yaml

定义**权限策略**，包括行级过滤和列级敏感字段。

```yaml
users:
  user_001:
    row_filters:
      region:
        operator: "="
        value: "HD"
    tenant_id: "tenant_a"

sensitive_columns:
  phone:
    description: "手机号"

masking_rules:
  phone: "lambda x: x[:3] + '****' + x[-4:]"
```

### users 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `row_filters` | dict | ❌ | 行级过滤条件，field → {operator, value} |
| `tenant_id` | string | ❌ | 租户隔离标识 |

### sensitive_columns 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `description` | string | ❌ | 敏感字段说明 |

### masking_rules 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| key | string | ✅ | 字段名 |
| value | string | ✅ | Python lambda 表达式字符串 |

---

## history.yaml

提供 **few-shot 示例**，用于 RAG 检索增强。

```yaml
examples:
  - question: "查询华东地区的销售额"
    dsl:
      data_source: orders
      metrics:
        - func: sum
          field: pay_amount
          alias: sales_amount
      filters:
        - field: region
          operator: "="
          value: "华东"
```

### examples 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `question` | string | ✅ | 自然语言问题 |
| `dsl` | dict | ✅ | 对应的 DSL |

---

## 配置生效机制

1. **修改配置** → 编辑 `configs/*.yaml`
2. **重启服务** → 自动触发自检同步
3. **增量同步** → 仅加载变更的配置，避免重复加载向量模型
4. **实时生效** → 新查询立即使用最新配置

> 无需改代码即可新增指标、维度、意图、术语。
