# 20. DSL 规范

## 20.1 DSL 定位

DSL 用于描述"业务语义意图"，而不是最终 SQL。LLM 只负责生成 DSL，SQL 由系统编译生成。

## 20.2 DSL Schema

核心字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `metrics` | `list[Aggregation]` | 聚合指标，如 `sum(order_amount)` |
| `dimensions` | `list[str]` | 分组维度，如 `product_name` |
| `filters` | `list[Filter]` | 过滤条件 |
| `order_by` | `list[OrderBy]` | 排序规则 |
| `limit` | `int` | 默认 100，最大 10000 |
| `offset` | `int` | 默认 0 |
| `data_source` | `str` | 语义模型名，如 `"orders"` |
| `post_process` | `PostProcess` | 基础 SQL 聚合完成后的受控高级分析 |

子类型定义：

- `Aggregation`: `{func: "sum"/"avg"/"count"/"min"/"max", field: str, alias: str}`
- `Filter`: `{field: str, operator: "="/"!="/">"/"<"/">="/<="/"between"/"in"/"like", value: any}`
- `OrderBy`: `{field: str, direction: "asc"/"desc"}`
- `PostProcess`:
  - 分组 TopN：`{type: "group_top_n", metric: str, group_by: list[str], top_n: int, direction: "asc"/"desc"}`
  - 占比：`{type: "proportion", metric: str, output_field: str}`

`post_process` 不是自由表达式，也不会直接拼接 SQL。它只能引用当前 DSL 已输出的指标别名和维度，由系统在 SQL 执行后进行受控计算。

## 20.3 示例

用户问题："查询华东地区 2024Q1 销售额最高的 10 个产品"

生成 DSL：
```json
{
  "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
  "dimensions": ["product_name"],
  "filters": [
    {"field": "region", "operator": "=", "value": "华东"},
    {"field": "order_date", "operator": "between", "value": ["2024-01-01", "2024-03-31"]}
  ],
  "order_by": [{"field": "sales_amount", "direction": "desc"}],
  "limit": 10,
  "data_source": "orders"
}
```

## 20.4 高级分析示例

### 各品类销售额最高的产品

```json
{
  "metrics": [
    {"func": "sum", "field": "order_amount", "alias": "sales_amount"}
  ],
  "dimensions": ["category", "product_name"],
  "order_by": [{"field": "sales_amount", "direction": "desc"}],
  "data_source": "orders",
  "post_process": {
    "type": "group_top_n",
    "metric": "sales_amount",
    "group_by": ["category"],
    "top_n": 1,
    "direction": "desc"
  }
}
```

### 各品类销售额占总销售额比例

```json
{
  "metrics": [
    {"func": "sum", "field": "order_amount", "alias": "sales_amount"}
  ],
  "dimensions": ["category"],
  "data_source": "orders",
  "post_process": {
    "type": "proportion",
    "metric": "sales_amount",
    "output_field": "sales_amount_proportion"
  }
}
```

占比结果为 0-1 小数。分母是当前查询过滤、权限和时间范围生效后，所有返回分组指标值之和。
