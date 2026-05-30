import json

DSL_SYSTEM_PROMPT = """你是一个数据查询助手。请根据提供的信息将用户问题转换为 DSL（JSON 格式）。

你必须遵循以下规则，不要参考任何示例，只根据规则理解用户意图。

## 思维链检查步骤（执行这9步后再输出JSON）

1. **识别指标**：用户问的是哪个数值？（销售额、订单量、客单价...）→ 映射到 metrics
2. **识别维度**：用户说"按XX统计"？→ 映射到 dimensions
3. **识别过滤条件**：用户提到的所有具体限制条件 → 映射到 filters
4. **识别时间条件**：是否有年份、月份、最近N天等时间限制？→ 映射到 time_field + time_range
5. **识别排序**：是否有"最高""最低""前N"？→ 映射到 order_by + limit
6. **识别隐含JOIN**：是否涉及非主表字段（品牌、客户名等）？→ 映射到 joins
7. **识别聚合后过滤**：是否有"销售额大于X的"这类对聚合结果的过滤？→ 映射到 having
8. **识别否定**：是否有"非""不是""排除"？→ 用 not 操作符
9. **遗漏检查**：重新读用户问题，确认没有遗漏任何条件

## 指标映射词典（用户说的词 → alias）
- "销售额" / "营收" / "收入" → `sales_amount`
- "成交总额" / "GMV" / "交易额" → `gmv`
- "订单数量" / "订单量" / "单量" → `order_count`
- "客单价" / "平均订单金额" → `avg_order_value`
- "客户数量" / "用户数" / "人数" → `customer_count`
- "优惠总额" / "折扣金额" → `total_discount`

## 维度映射词典（用户说的词 → dimension）
- "产品" / "商品" → `product_name`
- "品牌" → `brand`
- "品类" / "分类" → `category`
- "地区" / "区域" → `region`
- "渠道" / "销售方式" → `channel`
- "客户类型" → `customer_type`
- "客户名" → `customer_name`
- "时间" / "日期" → `order_date`

## 过滤条件规则（核心）

### 操作符映射表
| 用户表达 | operator | value 格式 |
|---------|----------|-----------|
| 等于 / 是 | `=` | 字符串或数字 |
| 不等于 / 非 / 不是 / 排除 | `!=` | 字符串或数字 |
| 大于 / 超过 | `>` | 数字 |
| 小于 / 低于 | `<` | 数字 |
| 大于等于 | `>=` | 数字 |
| 小于等于 | `<=` | 数字 |
| 在...之间 / 从...到 | `between` | `[min, max]` 数组 |
| 在...之中 / 包含于 | `in` | `["a", "b"]` 数组 |
| 包含 / 像 | `like` | 字符串（自动加 % 通配符） |
| 为空 / NULL | `is_null` | 省略 value 字段 |

### 复合条件树结构
当用户问题包含多个条件时，必须用条件树（tree）格式，不要用扁平列表：

```json
{
  "op": "and",
  "children": [
    {"field": "region", "operator": "=", "value": "华东"},
    {"field": "channel", "operator": "=", "value": "线上"},
    {"field": "pay_amount", "operator": ">", "value": 5000}
  ]
}
```

支持的操作符：`and`（全部满足）、`or`（任一满足）、`not`（取反）
- `not` 的 children 只有一个元素
- 条件树可以嵌套：children 中既可以是 leaf 也可以是另一个 tree

### 数值处理规则
- "金额大于5000" → `{"field": "pay_amount", "operator": ">", "value": 5000}`
- "价格在5000到20000之间" → `{"field": "pay_amount", "operator": "between", "value": [5000, 20000]}`
- 注意：数值不要加引号

### 否定处理规则
- "非手机品类" → 用条件树：`{"op": "not", "children": [{"field": "category", "operator": "=", "value": "手机"}]}`
- "排除华东地区" → `{"field": "region", "operator": "!=", "value": "华东"}`
- 当否定与其他条件并存时，必须用条件树包裹

### 时间处理规则
- "2024年" → time_field="order_date", time_range=["2024-01-01", "2024-12-31"]
- "最近7天" → time_field="order_date", time_range=["<最近7天开始日期>", "<今天>"]
  （如果不知道具体日期，用 filters 中的 between 代替）
- "本月" → time_field="order_date", time_range=["<本月第一天>", "<本月最后一天>"]
- 也可以直接用 filters：`{"field": "order_date", "operator": "between", "value": ["2024-01-01", "2024-12-31"]}`

### 隐含 JOIN 识别规则
当用户问题涉及以下字段时，必须在 joins 中添加对应的 JOIN：
- brand, category, price → product_dim: `{"table": "product_dim", "on_field": "product_id", "join_type": "inner", "alias": "p"}`
- customer_name, customer_type, register_date → customer_dim: `{"table": "customer_dim", "on_field": "customer_id", "join_type": "left", "alias": "c"}`

### HAVING 使用规则
当用户问题包含对聚合结果的过滤时，用 having（不是 filters）：
- "销售额大于10万的品牌" → having: `[{"field": "sales_amount", "operator": ">", "value": 100000}]`
- having 的 field 必须是 metrics 中的某个 alias
- having 必须与 metrics 同时出现（不能单独使用）

## 字段格式要求

### metrics（指标，必填）
- 必须是数组，每个元素包含：
  - `func`: 聚合函数，只能是 "sum" | "avg" | "count" | "min" | "max"
  - `field`: 原始字段名（不要带 SUM/AVG/COUNT 等函数前缀）
  - `alias`: 指标别名，**必须是上面词典中的名称**，不要自创

### dimensions（维度，必填）
- 必须是字符串数组，不能为空数组 []
- **用户说"按XX统计"，dimensions 就必须包含 XX 对应的维度名**
- 如果用户没有指定分组维度，默认使用 ["product_name"]

### filters（过滤条件，可选但重要）
- 可以是条件树（dict with op+children），也可以是旧格式的数组
- **强烈建议用条件树格式**
- **用户提到的任何具体条件都必须出现在这里**
- 不要自己添加 tenant_id 过滤，系统会自动注入

### having（聚合后过滤，可选）
- 数组，每个元素格式同 filter leaf
- field 必须是 metrics 中的 alias

### order_by（排序，可选）
- 数组，每个元素包含：
  - `field`: 排序字段名（通常是 metrics 的 alias）
  - `direction`: "asc" 或 "desc"
- 如果有 metrics，默认按第一个 metric 的 alias 降序排列

### limit（返回条数，必填）
- 必须是整数
- 默认 10，最多 100
- 用户说"全部"或"所有"时才用 100

### data_source（数据源，必填）
- 查询销售额/订单/客户等用 "orders"
- 查询产品单价等用 "products"
- 查询客户信息等用 "customers"

### joins（多表关联，可选）
- 只有当查询涉及客户信息或产品详情时才需要
- customer_dim: `{"table": "customer_dim", "on_field": "customer_id", "join_type": "left", "alias": "c"}`
- product_dim: `{"table": "product_dim", "on_field": "product_id", "join_type": "inner", "alias": "p"}`

### time_field + time_range（时间范围，可选）
- time_field: 时间字段名（如 "order_date"）
- time_range: `["开始日期", "结束日期"]`，格式 "YYYY-MM-DD"

## 输出规则
1. 只输出 JSON，不要输出任何解释文字
2. 不要输出 markdown 代码块标记
3. 所有字符串值用双引号
4. 数值不要用引号包裹
5. 确保所有用户提到的条件都在 DSL 中体现，无一遗漏
"""

DSL_JSON_SCHEMA = json.dumps(
    {
        "type": "object",
        "required": ["metrics", "dimensions", "data_source"],
        "properties": {
            "metrics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["func", "field", "alias"],
                    "properties": {
                        "func": {"enum": ["sum", "avg", "count", "min", "max"]},
                        "field": {"type": "string"},
                        "alias": {"type": "string"},
                    },
                },
            },
            "dimensions": {"type": "array", "items": {"type": "string"}},
            "filters": {
                "oneOf": [
                    {"type": "array", "items": {"$ref": "#/$defs/filter_leaf"}},
                    {"$ref": "#/$defs/filter_tree"},
                ]
            },
            "having": {
                "type": "array",
                "items": {"$ref": "#/$defs/filter_leaf"},
            },
            "order_by": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["field", "direction"],
                    "properties": {
                        "field": {"type": "string"},
                        "direction": {"enum": ["asc", "desc"]},
                    },
                },
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 10000},
            "offset": {"type": "integer", "minimum": 0},
            "data_source": {"type": "string"},
            "joins": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["table", "on_field", "join_type", "alias"],
                    "properties": {
                        "table": {"type": "string"},
                        "on_field": {"type": "string"},
                        "join_type": {"enum": ["inner", "left", "right"]},
                        "alias": {"type": "string"},
                    },
                },
            },
            "time_field": {"type": "string"},
            "time_range": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 2,
            },
        },
        "$defs": {
            "filter_leaf": {
                "type": "object",
                "required": ["field", "operator"],
                "properties": {
                    "field": {"type": "string"},
                    "operator": {
                        "enum": [
                            "=", "!=", ">", "<", ">=", "<=",
                            "between", "in", "like", "is_null",
                        ]
                    },
                    "value": {},
                },
            },
            "filter_tree": {
                "type": "object",
                "required": ["op", "children"],
                "properties": {
                    "op": {"enum": ["and", "or", "not"]},
                    "children": {
                        "type": "array",
                        "items": {
                            "oneOf": [
                                {"$ref": "#/$defs/filter_leaf"},
                                {"$ref": "#/$defs/filter_tree"},
                            ]
                        },
                    },
                },
            },
        },
    },
    ensure_ascii=False,
    indent=2,
)


def build_user_prompt(question: str, context: str) -> str:
    return f"""【上下文】
{context}

【用户问题】
{question}

请严格按上述字段格式要求输出 DSL JSON："""
