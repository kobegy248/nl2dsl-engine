下面是一份偏企业架构风格的《NL2DSL + Calcite 智能问数系统方案文档》Markdown 版本，可以直接继续扩展成技术方案、架构评审文档或项目 README。

---

# 企业级 NL2DSL 智能问数系统方案

## 1. 背景

传统 NL2SQL（自然语言转 SQL）方案通常采用：

```text id="jlwm1n"
用户问题 -> LLM -> SQL -> 数据库
```

该方案在 Demo 阶段效果较好，但在企业生产环境中存在大量问题：

* SQL 不可校验
* 权限不可控
* 查询性能不可治理
* 多数据库方言适配困难
* 指标口径不统一
* 出错不可定位
* LLM 输出不稳定

因此：

# 企业级智能问数系统不应直接生成 SQL

而应采用：

```text id="jlwm1l"
用户问题
 -> LLM
 -> DSL
 -> Query Planner
 -> Calcite
 -> SQL
 -> Database
```

核心思想：

> AI 负责语义理解，系统负责执行治理。

---

# 2. 总体架构

## 2.1 架构图

```text id="jlwm1j"
┌─────────────────┐
│ Natural Language │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ LLM Intent Parse │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Semantic DSL(IR) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Schema Validator │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Permission Layer │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Query Planner    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Apache Calcite   │
│ Relational IR    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ SQL Compiler     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ ClickHouse/MySQL │
└─────────────────┘
```

---

# 3. 核心设计目标

## 3.1 可校验

所有查询必须：

* 字段合法
* 指标合法
* 操作符合法
* LIMIT 合法
* 权限合法

禁止：

```sql id="jlwm1h"
SELECT * FROM salary
```

直接进入数据库。

---

## 3.2 可优化

系统需支持：

* Predicate Pushdown
* Projection Pushdown
* Join Reorder
* Materialized View Rewrite
* Cache Routing
* Aggregation Rewrite

---

## 3.3 可治理

支持：

* 行级权限
* 列级权限
* 数据脱敏
* 租户隔离
* 审计日志
* SQL 风险控制

---

## 3.4 可扩展

支持：

* 多数据库方言
* 多指标体系
* 多语义模型
* 多 Agent 接入

---

# 4. DSL 设计

## 4.1 DSL 定位

DSL（Domain Specific Language）用于描述：

# “业务语义意图”

而不是最终 SQL。

---

## 4.2 DSL 示例

用户问题：

> 查询华东地区 2024Q1 销售额最高的 10 个产品

对应 DSL：

```json id="jlwm1f"
{
  "metric": "sales_amount",
  "group_by": ["product_name"],
  "filters": [
    {
      "field": "region",
      "operator": "=",
      "value": "华东"
    },
    {
      "field": "order_date",
      "operator": "between",
      "value": [
        "2024-01-01",
        "2024-03-31"
      ]
    }
  ],
  "order_by": {
    "field": "sales_amount",
    "direction": "desc"
  },
  "limit": 10
}
```

---

# 5. Semantic Layer 设计

## 5.1 指标注册

采用 YAML 定义指标：

```yaml id="jlwm1d"
metrics:
  sales_amount:
    expr: SUM(order_amount)

  gmv:
    expr: SUM(pay_amount)

dimensions:
  product_name:
    column: product_name

  region:
    column: region
```

---

## 5.2 指标展开

DSL：

```json id="jlwm1b"
{
  "metric": "gmv"
}
```

Semantic Layer 自动展开：

```text id="jlwm19"
SUM(pay_amount)
```

---

# 6. DSL 校验层

## 6.1 Schema 校验

校验：

* metric 是否存在
* dimension 是否存在
* operator 是否合法
* filter 类型是否匹配

---

## 6.2 风险控制

禁止：

* 全表扫描
* 无 LIMIT 查询
* 超长时间范围
* 敏感字段访问

---

## 6.3 权限控制

自动注入：

```json id="jlwm17"
{
  "field": "region",
  "operator": "=",
  "value": "华东"
}
```

实现：

* Row Level Security
* Column Level Security

---

# 7. Query Planner

## 7.1 功能

负责：

* Join 推导
* 聚合路由
* 预聚合表命中
* Cache 命中
* 时间范围限制
* Query Rewrite

---

## 7.2 逻辑计划

DSL：

```json id="jlwm15"
{
  "metric": "sales_amount"
}
```

转换为：

```text id="jlwm13"
Aggregate
 └── Scan(order_fact)
```

---

# 8. Apache Calcite 集成

## 8.1 Calcite 定位

Apache Calcite 用于：

* Relational Algebra
* Query Optimization
* SQL Compilation

---

## 8.2 Calcite Logical Plan

通过 RelBuilder 构建：

```java id="jlwm11"
RelBuilder builder = ...

builder
    .scan("orders")
    .filter(
        builder.equals(
            builder.field("region"),
            builder.literal("华东")
        )
    )
    .aggregate(
        builder.groupKey("product_name"),
        builder.sum(false, "sales_amount",
            builder.field("amount"))
    );

RelNode relNode = builder.build();
```

---

## 8.3 生成 RelNode

生成：

```text id="jlwm0z"
LogicalAggregate
 └── LogicalFilter
      └── LogicalTableScan
```

---

## 8.4 Optimizer

Calcite 自动执行：

* Filter Pushdown
* Projection Pushdown
* Join Reorder
* Aggregate Rewrite

---

## 8.5 SQL Compiler

最终生成目标数据库 SQL：

```sql id="jlwm0x"
SELECT product_name,
       SUM(amount) AS sales_amount
FROM orders
WHERE region = '华东'
GROUP BY product_name
ORDER BY sales_amount DESC
LIMIT 10
```

---

# 9. 多数据库适配

## 9.1 支持数据库

支持：

* ClickHouse
* MySQL
* PostgreSQL
* Doris
* Hive
* SparkSQL
* Trino

---

## 9.2 方言适配

通过：

```text id="jlwm0v"
SqlDialect
```

实现：

* LIMIT 差异
* 时间函数差异
* JSON 函数差异
* 聚合函数差异

---

# 10. LLM 设计

## 10.1 LLM 只负责 DSL

禁止：

```text id="jlwm0t"
LLM -> SQL
```

采用：

```text id="jlwm0r"
LLM -> DSL
```

---

## 10.2 Prompt 内容

Prompt 包含：

* Schema
* Metric 定义
* 示例 DSL
* 权限信息
* 业务术语

---

## 10.3 输出格式

要求：

```text id="jlwm0p"
JSON ONLY
```

通过：

* JSON Schema
* Pydantic
* Structured Output

保证格式稳定。

---

# 11. RAG 设计

## 11.1 检索内容

检索：

* 表结构
* 指标定义
* 历史 DSL
* 历史 SQL
* 数据血缘
* 用户常用查询

---

## 11.2 向量召回

向量库：

* Milvus
* Qdrant
* pgvector

---

# 12. 安全设计

## 12.1 SQL 审计

记录：

* 用户
* DSL
* SQL
* 执行耗时
* 扫描数据量

---

## 12.2 敏感字段控制

禁止访问：

* salary
* phone
* id_card

---

## 12.3 Query Cost 控制

限制：

* Scan Rows
* CPU Time
* Memory Usage

---

# 13. 反馈闭环

## 13.1 错误沉淀

记录：

* 用户问题
* 错误 DSL
* 修正 DSL
* 修正 SQL

---

## 13.2 自动学习

用于：

* Few-shot 增强
* Schema Linking
* Query Rewrite

---

# 14. 推荐技术栈

| 模块             | 技术                  |
| -------------- | ------------------- |
| LLM            | GPT / Qwen / Claude |
| DSL 校验         | Pydantic            |
| Query Planner  | 自定义                 |
| Query Compiler | Apache Calcite      |
| Semantic Layer | MetricFlow          |
| Warehouse      | ClickHouse          |
| Vector DB      | Qdrant              |
| API            | FastAPI             |
| Workflow       | LangGraph           |

---

# 15. 推荐执行链路

```text id="jlwm0n"
User
 -> LLM
 -> DSL
 -> Validator
 -> Semantic Layer
 -> Query Planner
 -> Calcite RelNode
 -> Optimizer
 -> SQL Compiler
 -> ClickHouse
 -> Result Formatter
```

---

# 16. 与传统 NL2SQL 对比

| 能力       | 传统 NL2SQL | DSL + Calcite |
| -------- | --------- | ------------- |
| SQL 可控性  | 差         | 强             |
| 权限治理     | 弱         | 强             |
| Query 优化 | 基本没有      | 完整支持          |
| 多数据库适配   | 困难        | 简单            |
| 可调试性     | 差         | 强             |
| 企业落地     | 困难        | 可生产化          |

---

# 17. 总结

企业级智能问数系统的核心：

不是：

```text id="jlwm0k"
自然语言 -> SQL
```

而是：

```text id="jlwm0i"
自然语言
 -> Semantic DSL
 -> Query Planner
 -> Relational Algebra
 -> SQL Compiler
 -> Execution
```

本质上：

# AI 负责语义理解

# Calcite 负责查询编译

# 数据库负责执行

最终实现：

* 可治理
* 可审计
* 可优化
* 可扩展
* 可生产化

的企业级 AI Query Engine。

