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

子类型定义：

- `Aggregation`: `{func: "sum"/"avg"/"count"/"min"/"max", field: str, alias: str}`
- `Filter`: `{field: str, operator: "="/"!="/">"/"<"/">="/<="/"between"/"in"/"like", value: any}`
- `OrderBy`: `{field: str, direction: "asc"/"desc"}`

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
