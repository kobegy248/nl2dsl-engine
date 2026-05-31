# NL2DSL E2E 端到端测试报告

> 生成时间: 2026-05-30 21:03:56

---

## 1. 测试汇总

| 指标 | 数值 |
|------|------|
| 总测试数 | 253 |
| 通过 | 253 |
| 失败 | 0 |
| 错误 | 0 |
| 跳过 | 0 |
| XFAIL | 0 |

tests/e2e/test_agent_coverage.py::TestErrorRecovery::test_invalid_dsl_returns_400 PASSED [ 18%]

---

## 2. 失败测试详情

🎉 所有测试通过，无失败项！

---

## 3. 查询链路（Trace）分析

### 简单查询 - 查询销售额

- **类型**: simple
- **端点**: /api/v1/query
- **HTTP状态**: 200
- **响应状态**: success
- **执行时间**: 25 ms

**DSL**:
```json
{
  "metrics": [
    {
      "func": "sum",
      "field": "SUM(pay_amount)",
      "alias": "sales_amount"
    }
  ],
  "dimensions": [
    "product_name"
  ],
  "filters": [
    {
      "field": "region_code",
      "operator": "in",
      "value": [
        "HD",
        "HN"
      ]
    },
    {
      "field": "tenant_id",
      "operator": "=",
      "value": "t001"
    }
  ],
  "order_by": [
    {
      "field": "sales_amount",
      "direction": "desc"
    }
  ],
  "limit": 10,
  "offset": 0,
  "data_source": "orders",
  "time_field": null,
  "time_range": null,
  "joins": null
}
```

**SQL**:
```sql
SELECT order_fact.product_name AS product_name, sum(order_fact.pay_amount) AS sales_amount 
FROM order_fact 
WHERE order_fact.region_code IN ('HD', 'HN') AND order_fact.tenant_id = 't001' GROUP BY order_fact.product_name ORDER BY sales_amount DESC
 LIMIT 10 OFFSET 0
```

**数据预览** (共 7 行):
```json
[
  {
    "product_name": "iPhone 15 Pro",
    "sales_amount": 71991.0
  },
  {
    "product_name": "华为 Mate 60 Pro",
    "sales_amount": 55292.1
  },
  {
    "product_name": "海尔冰箱 500L",
    "sales_amount": 30792.3
  }
]
```

**解释**: 您的问题是'查询销售额'。基于关键词识别为 'single_query' 意图，将问题分解为 1 个子查询。查询结果为：product_name=iPhone 15 Pro, sales_amount=71991.0; product_name=华为 Mate 60 Pro, sales_amount=55292.1; product_name=海尔冰箱 500L, sales_amount=30792.3 ...（共7条数据）

**置信度**: 0.5

---

### 复杂查询 - 对比华东和华南的销售额

- **类型**: complex_compare
- **端点**: /api/v1/query
- **HTTP状态**: 200
- **响应状态**: success
- **执行时间**: 57 ms

**数据预览** (共 10 行):
```json
[
  {
    "product_name": "华为 Mate 60 Pro",
    "sales_amount": 41294.1,
    "__sub_query_id": "sq-1"
  },
  {
    "product_name": "iPhone 15 Pro",
    "sales_amount": 31996.0,
    "__sub_query_id": "sq-1"
  },
  {
    "product_name": "海尔冰箱 500L",
    "sales_amount": 27193.2,
    "__sub_query_id": "sq-1"
  }
]
```

**解释**: 您的问题是'对比华东和华南的销售额'。基于意图配置 'compare'（分解策略: split_by_objects），将问题分解为 2 个子查询。其中，华东的销售额：共6个产品，销售额合计约115,561.2元；华南的销售额：共4个产品，销售额合计约70,412.4元。

**置信度**: 0.5

---

### 趋势查询 - 销售额趋势

- **类型**: complex_trend
- **端点**: /api/v1/query
- **HTTP状态**: 200
- **响应状态**: success
- **执行时间**: 27 ms

**数据预览** (共 10 行):
```json
[
  {
    "order_date": "2024-01-17",
    "sales_amount": 39995.0,
    "__sub_query_id": "sq-1"
  },
  {
    "order_date": "2024-01-05",
    "sales_amount": 31996.0,
    "__sub_query_id": "sq-1"
  },
  {
    "order_date": "2024-01-30",
    "sales_amount": 27996.0,
    "__sub_query_id": "sq-1"
  }
]
```

**解释**: 您的问题是'销售额趋势'。基于意图配置 'trend'（分解策略: single_with_time_grouping），将问题分解为 1 个子查询。数据呈下降趋势，从39995.0下降至3599.1。

**置信度**: 0.5

---

### 关联查询 - 销售额和订单量的关系

- **类型**: complex_correlation
- **端点**: /api/v1/query
- **HTTP状态**: 200
- **响应状态**: success
- **执行时间**: 60 ms

**数据预览** (共 14 行):
```json
[
  {
    "product_name": "iPhone 15 Pro",
    "sales_amount": 71991.0,
    "__sub_query_id": "sq-1"
  },
  {
    "product_name": "华为 Mate 60 Pro",
    "sales_amount": 55292.1,
    "__sub_query_id": "sq-1"
  },
  {
    "product_name": "海尔冰箱 500L",
    "sales_amount": 30792.3,
    "__sub_query_id": "sq-1"
  }
]
```

**解释**: 您的问题是'销售额和订单量的关系'。基于意图配置 'correlation'（分解策略: split_by_objects），将问题分解为 2 个子查询。数据点不足，无法计算相关性。

**置信度**: 0.5

---

### DSL生成 - 查询华东地区的销售额

- **类型**: dsl_generate
- **端点**: /api/v1/query/dsl
- **HTTP状态**: 200
- **响应状态**: success
- **执行时间**: 18 ms

**DSL**:
```json
{
  "metrics": [
    {
      "func": "sum",
      "field": "SUM(pay_amount)",
      "alias": "sales_amount"
    }
  ],
  "dimensions": [
    "region"
  ],
  "filters": [
    {
      "field": "region_code",
      "operator": "=",
      "value": "HD"
    },
    {
      "field": "region_code",
      "operator": "in",
      "value": [
        "HD",
        "HN"
      ]
    },
    {
      "field": "tenant_id",
      "operator": "=",
      "value": "t001"
    }
  ],
  "order_by": [
    {
      "field": "sales_amount",
      "direction": "desc"
    }
  ],
  "limit": 10,
  "offset": 0,
  "data_source": "orders",
  "time_field": null,
  "time_range": null,
  "joins": null
}
```

---

### DSL执行 - 按品牌汇总销售额

- **类型**: dsl_execute
- **端点**: /api/v1/query/execute
- **HTTP状态**: 200
- **响应状态**: success
- **执行时间**: 27 ms

**SQL**:
```sql
SELECT order_fact.brand AS brand, sum(order_fact.pay_amount) AS sales_amount 
FROM order_fact 
WHERE order_fact.region_code IN ('HD', 'HN') AND order_fact.tenant_id = 't001' GROUP BY order_fact.brand
 LIMIT 100 OFFSET 0
```

**数据预览** (共 7 行):
```json
[
  {
    "brand": "Nike",
    "sales_amount": 1438.4
  },
  {
    "brand": "优衣库",
    "sales_amount": 4041.9
  },
  {
    "brand": "华为",
    "sales_amount": 55292.1
  }
]
```

---

### 权限测试 - u001(华东/华南)

- **类型**: permission_u001
- **端点**: /api/v1/query
- **HTTP状态**: 200
- **响应状态**: success
- **执行时间**: 27 ms

**DSL**:
```json
{
  "metrics": [
    {
      "func": "sum",
      "field": "SUM(pay_amount)",
      "alias": "sales_amount"
    }
  ],
  "dimensions": [
    "region"
  ],
  "filters": [
    {
      "field": "region_code",
      "operator": "in",
      "value": [
        "HD",
        "HN"
      ]
    },
    {
      "field": "tenant_id",
      "operator": "=",
      "value": "t001"
    }
  ],
  "order_by": [
    {
      "field": "sales_amount",
      "direction": "desc"
    }
  ],
  "limit": 10,
  "offset": 0,
  "data_source": "orders",
  "time_field": null,
  "time_range": null,
  "joins": null
}
```

**SQL**:
```sql
SELECT order_fact.region_code AS region, sum(order_fact.pay_amount) AS sales_amount 
FROM order_fact 
WHERE order_fact.region_code IN ('HD', 'HN') AND order_fact.tenant_id = 't001' GROUP BY order_fact.region_code ORDER BY sales_amount DESC
 LIMIT 10 OFFSET 0
```

**数据预览** (共 2 行):
```json
[
  {
    "region": "HD",
    "sales_amount": 115561.19999999998
  },
  {
    "region": "HN",
    "sales_amount": 70412.35
  }
]
```

**解释**: 您的问题是'查询各地区的销售额'。基于关键词识别为 'single_query' 意图，将问题分解为 1 个子查询。查询结果为：region=HD, sales_amount=115561.19999999998; region=HN, sales_amount=70412.35

**置信度**: 0.5

---

### 权限测试 - u002(华北/西南)

- **类型**: permission_u002
- **端点**: /api/v1/query
- **HTTP状态**: 200
- **响应状态**: success
- **执行时间**: 25 ms

**DSL**:
```json
{
  "metrics": [
    {
      "func": "sum",
      "field": "SUM(pay_amount)",
      "alias": "sales_amount"
    }
  ],
  "dimensions": [
    "region"
  ],
  "filters": [
    {
      "field": "region_code",
      "operator": "in",
      "value": [
        "HB",
        "XN"
      ]
    },
    {
      "field": "tenant_id",
      "operator": "=",
      "value": "t002"
    }
  ],
  "order_by": [
    {
      "field": "sales_amount",
      "direction": "desc"
    }
  ],
  "limit": 10,
  "offset": 0,
  "data_source": "orders",
  "time_field": null,
  "time_range": null,
  "joins": null
}
```

**SQL**:
```sql
SELECT order_fact.region_code AS region, sum(order_fact.pay_amount) AS sales_amount 
FROM order_fact 
WHERE order_fact.region_code IN ('HB', 'XN') AND order_fact.tenant_id = 't002' GROUP BY order_fact.region_code ORDER BY sales_amount DESC
 LIMIT 10 OFFSET 0
```

**数据预览** (共 2 行):
```json
[
  {
    "region": "HB",
    "sales_amount": 46996.2
  },
  {
    "region": "XN",
    "sales_amount": 35410.2
  }
]
```

**解释**: 您的问题是'查询各地区的销售额'。基于关键词识别为 'single_query' 意图，将问题分解为 1 个子查询。查询结果为：region=HB, sales_amount=46996.2; region=XN, sales_amount=35410.2

**置信度**: 0.5

---

### 跨表JOIN - 按客户类型统计销售额

- **类型**: join_customer
- **端点**: /api/v1/query/execute
- **HTTP状态**: 200
- **响应状态**: success
- **执行时间**: 21 ms

**SQL**:
```sql
SELECT order_fact.customer_type AS customer_type, sum(order_fact.pay_amount) AS sales_amount 
FROM order_fact JOIN customer_dim AS c ON order_fact.customer_id = c.customer_id 
WHERE order_fact.region_code IN ('HD', 'HN') AND order_fact.tenant_id = 't001' GROUP BY order_fact.customer_type
 LIMIT 100 OFFSET 0
```

**数据预览** (共 3 行):
```json
[
  {
    "customer_type": "VIP",
    "sales_amount": 33493.8
  },
  {
    "customer_type": "新客",
    "sales_amount": 116046.34999999999
  },
  {
    "customer_type": "老客",
    "sales_amount": 36433.4
  }
]
```

---

### 多维度分组 - 地区和品类

- **类型**: multi_dimension
- **端点**: /api/v1/query/execute
- **HTTP状态**: 200
- **响应状态**: success
- **执行时间**: 21 ms

**SQL**:
```sql
SELECT order_fact.region_code AS region, order_fact.category AS category, sum(order_fact.pay_amount) AS sales_amount 
FROM order_fact 
WHERE order_fact.region_code IN ('HD', 'HN') AND order_fact.tenant_id = 't001' GROUP BY order_fact.region_code, order_fact.category
 LIMIT 100 OFFSET 0
```

**数据预览** (共 5 行):
```json
[
  {
    "region": "HD",
    "category": "家电",
    "sales_amount": 27193.2
  },
  {
    "region": "HD",
    "category": "手机",
    "sales_amount": 82887.7
  },
  {
    "region": "HD",
    "category": "服饰",
    "sales_amount": 5480.3
  }
]
```

---

### 多指标 - 销售额和订单量

- **类型**: multi_metric
- **端点**: /api/v1/query/execute
- **HTTP状态**: 200
- **响应状态**: success
- **执行时间**: 21 ms

**SQL**:
```sql
SELECT order_fact.category AS category, sum(order_fact.pay_amount) AS sales_amount, count(order_fact.id) AS order_count 
FROM order_fact 
WHERE order_fact.region_code IN ('HD', 'HN') AND order_fact.tenant_id = 't001' GROUP BY order_fact.category
 LIMIT 100 OFFSET 0
```

**数据预览** (共 3 行):
```json
[
  {
    "category": "家电",
    "sales_amount": 43612.549999999996,
    "order_count": 4
  },
  {
    "category": "手机",
    "sales_amount": 136880.7,
    "order_count": 7
  },
  {
    "category": "服饰",
    "sales_amount": 5480.3,
    "order_count": 2
  }
]
```

---

### 库存查询 - 按仓库类型统计

- **类型**: inventory
- **端点**: /api/v1/query/execute
- **HTTP状态**: 200
- **响应状态**: success
- **执行时间**: 21 ms

**SQL**:
```sql
SELECT inventory_fact.warehouse_type AS warehouse_type, sum(inventory_fact.stock_quantity) AS total_stock 
FROM inventory_fact 
WHERE inventory_fact.region_code IN ('HD', 'HN') AND inventory_fact.tenant_id = 't001' GROUP BY inventory_fact.warehouse_type
 LIMIT 100 OFFSET 0
```

**数据预览** (共 2 行):
```json
[
  {
    "warehouse_type": "中心仓",
    "total_stock": 2091
  },
  {
    "warehouse_type": "前置仓",
    "total_stock": 2772
  }
]
```

---

## 4. SSE 流式事件分析

### 简单查询流

- **问题**: 查询销售额
- **类型**: simple
- **HTTP状态**: 200
- **Content-Type**: text/event-stream; charset=utf-8
- **事件数量**: 13
- **事件类型**: ['update', 'update', 'update', 'update', 'update', 'update', 'update', 'update', 'update', 'update', 'update', 'update', 'update']

**事件详情**:

#### Event 1: `update`

```json
{
  "clarification": {
    "ambiguities": null,
    "trace": {
      "step": "clarification",
      "status": "skipped",
      "reason": "no_llm"
    }
  }
}
```

#### Event 2: `update`

```json
{
  "plan": {
    "plan": "intent='single_query' sub_queries=[SubQuery(id='sq-1', dsl=None, depends_on=[], description='查询销售额')] reasoning=\"基于关键词识别为 'single_query' 意图，将问题分解为 1 个子查询。\" requires_approval=False",
    "trace": {
      "step": "plan",
      "status": "success",
      "source": "fallback",
      "intent": "single_query",
      "sub_queries_count": 1
    }
  }
}
```

#### Event 3: `update`

```json
{
  "decompose": {
    "complexity": "simple",
    "trace": {
      "step": "decompose",
      "status": "skipped",
      "reason": "looks_simple"
    }
  }
}
```

#### Event 4: `update`

```json
{
  "validation": {
    "question": "查询销售额",
    "user_id": "u001",
    "tenant_id": "t001",
    "data_source": null,
    "ambiguities": null,
    "plan": "intent='single_query' sub_queries=[SubQuery(id='sq-1', dsl=None, depends_on=[], description='查询销售额')] reasoning=\"基于关键词识别为 'single_query' 意图，将问题分解为 1 个子查询。\" requires_approval=False",
    "dsl": "metrics=[Aggregation(func='sum', field='order_amount', alias='sales_amount')] dimensions=['product_name'] filters=None order_by=[OrderBy(field='sale...
}
```

#### Event 5: `update`

```json
{
  "permission_check": {
    "question": "查询销售额",
    "user_id": "u001",
    "tenant_id": "t001",
    "data_source": null,
    "ambiguities": null,
    "plan": "intent='single_query' sub_queries=[SubQuery(id='sq-1', dsl=None, depends_on=[], description='查询销售额')] reasoning=\"基于关键词识别为 'single_query' 意图，将问题分解为 1 个子查询。\" requires_approval=False",
    "dsl": "metrics=[Aggregation(func='sum', field='order_amount', alias='sales_amount')] dimensions=['product_name'] filters=[Filter(field='region', oper...
}
```

#### Event 6: `update`

```json
{
  "resolve_semantic": {
    "dsl": "metrics=[Aggregation(func='sum', field='SUM(pay_amount)', alias='sales_amount')] dimensions=['product_name'] filters=[Filter(field='region_code', operator='in', value=['HD', 'HN']), Filter(field='tenant_id', operator='=', value='t001')] order_by=[OrderBy(field='sales_amount', direction='desc')] limit=10 offset=0 data_source='orders' time_field=None time_range=None joins=None",
    "trace": {
      "step": "resolve_semantic",
      "status": "success"
    }
 ...
}
```

#### Event 7: `update`

```json
{
  "confidence": {
    "confidence": 0.5,
    "explanation": "DSL 质量评分: 50%; 语法正确性: 100%; 语义匹配度: 50%; 历史可信度: 1.00; 路由决策: 继续执行（置信度充足）",
    "trace": {
      "step": "confidence",
      "status": "success",
      "confidence": 0.5,
      "routing": "continue",
      "details": {
        "syntax_score": 1.0,
        "semantic_score": 0.5,
        "semantic_source": "neutral_no_llm",
        "history_score": 1.0
      }
    }
  }
}
```

#### Event 8: `update`

```json
{
  "build_sql": {
    "sql": "SELECT order_fact.product_name AS product_name, sum(order_fact.pay_amount) AS sales_amount \nFROM order_fact \nWHERE order_fact.region_code IN ('HD', 'HN') AND order_fact.tenant_id = 't001' GROUP BY order_fact.product_name ORDER BY sales_amount DESC\n LIMIT 10 OFFSET 0",
    "trace": {
      "step": "build_sql",
      "status": "success"
    }
  }
}
```

#### Event 9: `update`

```json
{
  "scan_sql": {
    "trace": {
      "step": "scan_sql",
      "status": "success"
    }
  }
}
```

#### Event 10: `update`

```json
{
  "sandbox_check": {
    "sandbox_result": "SandboxResult(passed=True, risks=[], sample_rows=[{'product_name': '华为 Mate 60 Pro', 'sales_amount': 73489.5}, {'product_name': 'iPhone 15 Pro', 'sales_amount': 58792.65}, {'product_name': 'MacBook Pro 14', 'sales_amount': 53996.4}, {'product_name': '小米 14', 'sales_amount': 33191.7}, {'product_name': '联想 ThinkPad X1', 'sales_amount': 29997.0}, {'product_name': '美的空调 1.5匹', 'sales_amount': 18623.1}, {'product_name': '索尼电视 65寸', 'sales_amount': 15297.4...
}
```

#### Event 11: `update`

```json
{
  "execute_sql": {
    "data": [
      {
        "product_name": "华为 Mate 60 Pro",
        "sales_amount": 73489.5
      },
      {
        "product_name": "iPhone 15 Pro",
        "sales_amount": 58792.65
      },
      {
        "product_name": "MacBook Pro 14",
        "sales_amount": 53996.4
      },
      {
        "product_name": "小米 14",
        "sales_amount": 33191.7
      },
      {
        "product_name": "联想 ThinkPad X1",
        "sales_amount": 29997.0
      },
      {
        "pr...
}
```

#### Event 12: `update`

```json
{
  "verify_dsl": {
    "verify_status": "skipped",
    "trace": {
      "step": "verify_dsl",
      "status": "skipped",
      "reason": "no_llm"
    }
  }
}
```

#### Event 13: `update`

```json
{
  "explain": {
    "explanation": "您的问题是'查询销售额'。基于关键词识别为 'single_query' 意图，将问题分解为 1 个子查询。查询结果为：product_name=华为 Mate 60 Pro, sales_amount=73489.5; product_name=iPhone 15 Pro, sales_amount=58792.65; product_name=MacBook Pro 14, sales_amount=53996.4 ...（共10条数据）",
    "trace": {
      "step": "explain",
      "status": "success",
      "source": "template",
      "intent": "single_query"
    }
  }
}
```

---

### 对比查询流

- **问题**: 对比华东和华南的销售额
- **类型**: compare
- **HTTP状态**: 200
- **Content-Type**: text/event-stream; charset=utf-8
- **事件数量**: 8
- **事件类型**: ['plan', 'sub_query_start', 'sub_query_start', 'sub_query_result', 'sub_query_result', 'aggregate', 'explain', 'result']

**事件详情**:

#### Event 1: `plan`

```json
{
  "plan": "intent='compare' sub_queries=[SubQuery(id='sq-1', dsl=None, depends_on=[], description='华东的销售额'), SubQuery(id='sq-2', dsl=None, depends_on=[], description='华南的销售额')] reasoning=\"基于意图配置 'compare'（分解策略: split_by_objects），将问题分解为 2 个子查询。\" requires_approval=False"
}
```

#### Event 2: `sub_query_start`

```json
{
  "sub_query_id": "sq-1",
  "description": "华东的销售额"
}
```

#### Event 3: `sub_query_start`

```json
{
  "sub_query_id": "sq-2",
  "description": "华南的销售额"
}
```

#### Event 4: `sub_query_result`

```json
{
  "sub_query_id": "sq-1",
  "status": "success",
  "data": [
    {
      "product_name": "华为 Mate 60 Pro",
      "sales_amount": 73489.5
    },
    {
      "product_name": "MacBook Pro 14",
      "sales_amount": 53996.4
    },
    {
      "product_name": "iPhone 15 Pro",
      "sales_amount": 39595.05
    },
    {
      "product_name": "小米 14",
      "sales_amount": 17195.7
    },
    {
      "product_name": "海尔冰箱 500L",
      "sales_amount": 7198.2
    },
    {
      "product_name": "美的空调 1.5...
}
```

#### Event 5: `sub_query_result`

```json
{
  "sub_query_id": "sq-2",
  "status": "success",
  "data": [
    {
      "product_name": "联想 ThinkPad X1",
      "sales_amount": 29997.0
    },
    {
      "product_name": "iPhone 15 Pro",
      "sales_amount": 19197.6
    },
    {
      "product_name": "小米 14",
      "sales_amount": 15996.0
    },
    {
      "product_name": "索尼电视 65寸",
      "sales_amount": 15297.45
    },
    {
      "product_name": "美的空调 1.5匹",
      "sales_amount": 13495.0
    },
    {
      "product_name": "海尔冰箱 500L",
 ...
}
```

#### Event 6: `aggregate`

```json
{
  "result": {
    "rows": [
      {
        "product_name": "华为 Mate 60 Pro",
        "sales_amount": 73489.5,
        "__sub_query_id": "sq-1"
      },
      {
        "product_name": "MacBook Pro 14",
        "sales_amount": 53996.4,
        "__sub_query_id": "sq-1"
      },
      {
        "product_name": "iPhone 15 Pro",
        "sales_amount": 39595.05,
        "__sub_query_id": "sq-1"
      },
      {
        "product_name": "小米 14",
        "sales_amount": 17195.7,
        "__sub_query_...
}
```

#### Event 7: `explain`

```json
{
  "explanation": "您的问题是'对比华东和华南的销售额'。基于意图配置 'compare'（分解策略: split_by_objects），将问题分解为 2 个子查询。其中，华东的销售额：共7个产品，销售额合计约200,644.9元；华南的销售额：共8个产品，销售额合计约107,065.9元。"
}
```

#### Event 8: `result`

```json
{
  "status": "success",
  "data": [
    {
      "product_name": "华为 Mate 60 Pro",
      "sales_amount": 73489.5,
      "__sub_query_id": "sq-1"
    },
    {
      "product_name": "MacBook Pro 14",
      "sales_amount": 53996.4,
      "__sub_query_id": "sq-1"
    },
    {
      "product_name": "iPhone 15 Pro",
      "sales_amount": 39595.05,
      "__sub_query_id": "sq-1"
    },
    {
      "product_name": "小米 14",
      "sales_amount": 17195.7,
      "__sub_query_id": "sq-1"
    },
    {
      ...
}
```

---

### 趋势查询流

- **问题**: 销售额趋势
- **类型**: trend
- **HTTP状态**: 200
- **Content-Type**: text/event-stream; charset=utf-8
- **事件数量**: 6
- **事件类型**: ['plan', 'sub_query_start', 'sub_query_result', 'aggregate', 'explain', 'result']

**事件详情**:

#### Event 1: `plan`

```json
{
  "plan": "intent='trend' sub_queries=[SubQuery(id='sq-1', dsl=None, depends_on=[], description='销售额趋势（按时间分组）')] reasoning=\"基于意图配置 'trend'（分解策略: single_with_time_grouping），将问题分解为 1 个子查询。\" requires_approval=False"
}
```

#### Event 2: `sub_query_start`

```json
{
  "sub_query_id": "sq-1",
  "description": "销售额趋势（按时间分组）"
}
```

#### Event 3: `sub_query_result`

```json
{
  "sub_query_id": "sq-1",
  "status": "success",
  "data": [
    {
      "order_date": "2024-01-13",
      "sales_amount": 53996.4
    },
    {
      "order_date": "2024-01-25",
      "sales_amount": 40844.3
    },
    {
      "order_date": "2024-01-17",
      "sales_amount": 33245.25
    },
    {
      "order_date": "2024-01-18",
      "sales_amount": 31996.0
    },
    {
      "order_date": "2024-01-26",
      "sales_amount": 29997.0
    },
    {
      "order_date": "2024-01-31",
      "sale...
}
```

#### Event 4: `aggregate`

```json
{
  "result": {
    "rows": [
      {
        "order_date": "2024-01-13",
        "sales_amount": 53996.4,
        "__sub_query_id": "sq-1"
      },
      {
        "order_date": "2024-01-25",
        "sales_amount": 40844.3,
        "__sub_query_id": "sq-1"
      },
      {
        "order_date": "2024-01-17",
        "sales_amount": 33245.25,
        "__sub_query_id": "sq-1"
      },
      {
        "order_date": "2024-01-18",
        "sales_amount": 31996.0,
        "__sub_query_id": "sq-1"
  ...
}
```

#### Event 5: `explain`

```json
{
  "explanation": "您的问题是'销售额趋势'。基于意图配置 'trend'（分解策略: single_with_time_grouping），将问题分解为 1 个子查询。数据呈下降趋势，从53996.4下降至12726.2。"
}
```

#### Event 6: `result`

```json
{
  "status": "success",
  "data": [
    {
      "order_date": "2024-01-13",
      "sales_amount": 53996.4,
      "__sub_query_id": "sq-1"
    },
    {
      "order_date": "2024-01-25",
      "sales_amount": 40844.3,
      "__sub_query_id": "sq-1"
    },
    {
      "order_date": "2024-01-17",
      "sales_amount": 33245.25,
      "__sub_query_id": "sq-1"
    },
    {
      "order_date": "2024-01-18",
      "sales_amount": 31996.0,
      "__sub_query_id": "sq-1"
    },
    {
      "order_date": ...
}
```

---

### 关联查询流

- **问题**: 销售额和订单量的关系
- **类型**: correlation
- **HTTP状态**: 200
- **Content-Type**: text/event-stream; charset=utf-8
- **事件数量**: 8
- **事件类型**: ['plan', 'sub_query_start', 'sub_query_start', 'sub_query_result', 'sub_query_result', 'aggregate', 'explain', 'result']

**事件详情**:

#### Event 1: `plan`

```json
{
  "plan": "intent='correlation' sub_queries=[SubQuery(id='sq-1', dsl=None, depends_on=[], description='销售额的关系'), SubQuery(id='sq-2', dsl=None, depends_on=[], description='订单量的关系')] reasoning=\"基于意图配置 'correlation'（分解策略: split_by_objects），将问题分解为 2 个子查询。\" requires_approval=False"
}
```

#### Event 2: `sub_query_start`

```json
{
  "sub_query_id": "sq-1",
  "description": "销售额的关系"
}
```

#### Event 3: `sub_query_start`

```json
{
  "sub_query_id": "sq-2",
  "description": "订单量的关系"
}
```

#### Event 4: `sub_query_result`

```json
{
  "sub_query_id": "sq-1",
  "status": "success",
  "data": [
    {
      "product_name": "华为 Mate 60 Pro",
      "sales_amount": 73489.5
    },
    {
      "product_name": "iPhone 15 Pro",
      "sales_amount": 58792.65
    },
    {
      "product_name": "MacBook Pro 14",
      "sales_amount": 53996.4
    },
    {
      "product_name": "小米 14",
      "sales_amount": 33191.7
    },
    {
      "product_name": "联想 ThinkPad X1",
      "sales_amount": 29997.0
    },
    {
      "product_name": "美的...
}
```

#### Event 5: `sub_query_result`

```json
{
  "sub_query_id": "sq-2",
  "status": "success",
  "data": [
    {
      "product_name": "小米 14",
      "order_count": 3
    },
    {
      "product_name": "华为 Mate 60 Pro",
      "order_count": 3
    },
    {
      "product_name": "iPhone 15 Pro",
      "order_count": 3
    },
    {
      "product_name": "美的空调 1.5匹",
      "order_count": 2
    },
    {
      "product_name": "海尔冰箱 500L",
      "order_count": 2
    },
    {
      "product_name": "优衣库羽绒服",
      "order_count": 2
    },
    {
   ...
}
```

#### Event 6: `aggregate`

```json
{
  "result": {
    "rows": [
      {
        "product_name": "华为 Mate 60 Pro",
        "sales_amount": 73489.5,
        "__sub_query_id": "sq-1"
      },
      {
        "product_name": "iPhone 15 Pro",
        "sales_amount": 58792.65,
        "__sub_query_id": "sq-1"
      },
      {
        "product_name": "MacBook Pro 14",
        "sales_amount": 53996.4,
        "__sub_query_id": "sq-1"
      },
      {
        "product_name": "小米 14",
        "sales_amount": 33191.7,
        "__sub_query_...
}
```

#### Event 7: `explain`

```json
{
  "explanation": "您的问题是'销售额和订单量的关系'。基于意图配置 'correlation'（分解策略: split_by_objects），将问题分解为 2 个子查询。数据点不足，无法计算相关性。"
}
```

#### Event 8: `result`

```json
{
  "status": "success",
  "data": [
    {
      "product_name": "华为 Mate 60 Pro",
      "sales_amount": 73489.5,
      "__sub_query_id": "sq-1"
    },
    {
      "product_name": "iPhone 15 Pro",
      "sales_amount": 58792.65,
      "__sub_query_id": "sq-1"
    },
    {
      "product_name": "MacBook Pro 14",
      "sales_amount": 53996.4,
      "__sub_query_id": "sq-1"
    },
    {
      "product_name": "小米 14",
      "sales_amount": 33191.7,
      "__sub_query_id": "sq-1"
    },
    {
      ...
}
```

---

## 5. 链路节点说明

LangGraph StateGraph 查询链路中的关键节点:

| 节点 | 说明 | trace 状态 |
|------|------|-----------|
| clarification | 歧义检测 | success / skipped |
| decompose | 复杂查询改写 | success / skipped |
| generate_dsl | LLM 生成 DSL | success (llm) / success (mock) |
| mock_dsl | Mock DSL 生成 | success |
| validate_dsl | DSL 校验 | success |
| inject_row_permission | 行级权限注入 | success |
| check_col_permission | 列级权限检查 | success |
| resolve_semantic | 语义解析 | success |
| build_sql | SQL 构建 | success |
| scan_sql | SQL 安全扫描 | success |
| execute_sql | SQL 执行 | success |
| simplify_dsl | DSL 简化(重试) | success |
| verify_dsl | DSL 执行后自检 | skipped / pass / warn / fail |

---

*报告由 collect_e2e_results.py 自动生成*
