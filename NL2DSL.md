# 企业级 NL2DSL 智能问数系统方案

## 1. 背景

传统 NL2SQL（自然语言转 SQL）方案通常采用：

```
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

**企业级智能问数系统不应直接生成 SQL**

而应采用：

```
用户问题
 -> RAG 检索（schema/metrics/terms/history）
 -> LLM
 -> DSL
 -> Schema Validator
 -> Permission Layer
 -> Semantic Resolver
 -> SQL Compiler (SQLAlchemy Core + sqlglot)
 -> Sandbox 沙箱预检
 -> Database
```

核心思想：

> **AI 负责语义理解，系统负责执行治理。**

---

## 2. 总体架构

### 2.1 架构图

```
┌─────────────────────────┐
│ Natural Language Input  │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ Clarification (歧义检测) │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ RAG Retrieval           │
│  ├─ schema   (jieba)    │
│  ├─ metrics  (jieba)    │
│  ├─ terms    (jieba)    │
│  └─ history  (整句语义) │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ LLM Intent Parse        │ (RAG context + question → JSON)
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ DSL Output Postprocess  │
│  ├─ parse markdown 代码块│
│  ├─ 字段补全 / 格式规整  │
│  └─ filter & limit 兜底  │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ Schema Validator        │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ Permission Layer        │ (行级注入 + 列级检查 + 脱敏)
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ Semantic Resolver       │ (alias → 表达式)
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ SQL Builder             │ (SQLAlchemy Core)
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ SQL Scanner + Sandbox   │ (静态扫描 + EXPLAIN 预检)
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ Executor → SQLite/...   │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ Audit Logger            │
└─────────────────────────┘
```

---

## 3. 核心设计目标

### 3.1 可校验

所有查询必须：

* 字段合法
* 指标合法
* 操作符合法
* LIMIT 合法
* 权限合法

禁止：

```sql
SELECT * FROM salary
```

直接进入数据库。

### 3.2 可优化

系统需支持：

* Predicate Pushdown
* Projection Pushdown
* Join Reorder
* Materialized View Rewrite
* Cache Routing
* Aggregation Rewrite

### 3.3 可治理

支持：

* 行级权限（按用户/租户自动注入过滤条件）
* 列级权限（敏感字段黑名单）
* 数据脱敏（手机号 / 邮箱 / 身份证号等模板化遮蔽）
* 租户隔离
* 审计日志（query_id + DSL + SQL + trace + 耗时）
* SQL 风险控制（沙箱预检 + 静态扫描）

### 3.4 可扩展

支持：

* 多数据库方言
* 多指标体系
* 多语义模型
* 多 Agent 接入
* **配置驱动**：业务术语 / 历史示例通过 YAML 维护，无需改代码

---

## 4. DSL 设计

### 4.1 DSL 定位

DSL（Domain Specific Language）用于描述：

**"业务语义意图"**

而不是最终 SQL。

### 4.2 DSL 示例

用户问题：

> 查询华东地区销售额最高的 10 个产品

对应 DSL：

```json
{
  "metrics": [
    {"func": "sum", "field": "order_amount", "alias": "sales_amount"}
  ],
  "dimensions": ["product_name"],
  "filters": [
    {"field": "region", "operator": "=", "value": "华东"}
  ],
  "order_by": [
    {"field": "sales_amount", "direction": "desc"}
  ],
  "limit": 10,
  "data_source": "orders",
  "joins": []
}
```

---

## 5. RAG 检索层

### 5.1 4 集合设计

| 集合 | 来源 | 内容 | 检索策略 |
|------|------|------|---------|
| `schema` | metrics.yaml | 维度 + 指标定义 | jieba 切词 + 向量近邻 |
| `metrics` | metrics.yaml | 指标计算式 | jieba 切词 + 向量近邻 |
| `terms` | terms.yaml | 业务术语 + 别名映射 | jieba 切词 + 向量近邻 |
| `history` | history.yaml | 问题→DSL 示例 | **整句语义检索** |

### 5.2 为什么用混合策略

- **短命名实体**（"brand"、"流水→gmv"）适合精准关键词匹配
- **完整问句**适合整句语义相似度（找表达不同但意图相同的示例）

### 5.3 启动自检同步

配置文件改动后**重启后端自动同步**：

```
.rag_sync_state.json 记录每个 YAML 的 mtime
启动时对比，过期 → 增量重灌该集合
都最新 → 跳过 BGE 模型加载，启动毫秒级返回
```

---

## 6. Semantic Layer 设计

### 6.1 指标注册

采用 YAML 定义指标：

```yaml
metrics:
  sales_amount:
    expr: SUM(order_amount)
    description: "销售额"
  gmv:
    expr: SUM(order_amount)
    description: "成交总额"

dimensions:
  product_name:
    column: product_name
    description: "产品名称"
  region:
    column: region
    description: "地区"
```

### 6.2 术语映射（核心 RAG 锚点）

```yaml
# configs/terms.yaml
terms:
  gmv:
    aliases: [GMV, 成交总额, 交易额, 流水, 交易总额]
    metric: gmv
    description: "成交总额 SUM(order_amount)"
  customer_count:
    aliases: [客户数, 用户数, 多少人, 客户数量]
    metric: customer_count
  ...
```

每个 alias 单独入库，向量检索能精准命中"流水 → gmv"。

### 6.3 历史示例（few-shot 素材）

```yaml
# configs/history.yaml
examples:
  - question: "各品牌的流水"
    dsl: {metrics: [{func: sum, field: order_amount, alias: gmv}], dimensions: [brand], ...}
  - question: "卖得最好的5款货"
    dsl: {metrics: [...], dimensions: [product_name], limit: 5, ...}
```

整句 embed，LLM 看着像葫芦画瓢。

---

## 7. DSL 校验层

### 7.1 Schema 校验

校验：

* metric 是否在注册表
* dimension 是否在注册表
* data_source 是否存在
* operator 是否合法
* filter 类型是否匹配

校验失败 → 自动触发 `correct_dsl` 修正循环，最多 3 次。

### 7.2 风险控制

禁止：

* 全表扫描（沙箱 EXPLAIN 预检）
* 无 LIMIT 大查询（自动注入默认 limit=10）
* 超长时间范围
* 敏感字段访问

### 7.3 权限控制

自动注入用户租户/区域过滤条件：

```json
{"field": "tenant_id", "operator": "=", "value": "t001"}
```

实现：

* Row Level Security（行级权限）
* Column Level Security（列级权限）
* Masking Rules（脱敏规则）

---

## 8. SQL 编译层（当前实现）

### 8.1 SQLAlchemy Core

```python
table = metadata.tables["order_fact"]
stmt = (
    select(table.c.product_name, func.sum(table.c.order_amount).label("sales_amount"))
    .where(table.c.region == "华东")
    .group_by(table.c.product_name)
    .order_by(desc("sales_amount"))
    .limit(10)
)
sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
```

### 8.2 方言适配

通过 `sqlglot.transpile()` 转换为目标数据库 SQL：

* SQLite
* MySQL
* PostgreSQL
* ClickHouse
* Hive / SparkSQL

### 8.3 未来演进：Calcite 集成

后续可引入 Apache Calcite 实现更复杂的优化：

* Filter Pushdown
* Projection Pushdown
* Join Reorder
* Aggregate Rewrite
* Materialized View Rewrite

目前 SQLAlchemy Core + sqlglot 已满足生产基本需求。

---

## 9. LLM 设计

### 9.1 LLM 只负责 DSL

禁止：

```
LLM -> SQL
```

采用：

```
LLM -> DSL (JSON)
```

### 9.2 Prompt 组成

System Prompt（`nl2dsl/llm/prompts.py`）：
* DSL 字段格式要求
* 指标 / 维度映射词典
* 过滤条件铁律
* 5+ 个 few-shot 示例

User Prompt（`rag/retriever.py:build_prompt`）：
* RAG 检索的 schema / metrics / terms / history context
* 用户问题
* 强制要求（"用户说'流水'必须用 alias=gmv"）

### 9.3 输出格式

要求：JSON ONLY

实际 LLM 可能返回大段解释 + markdown 代码块。`_parse_llm_output` 用正则从中提取 JSON，三层兜底：

1. 优先匹配 `\`\`\`json ... \`\`\`` 代码块
2. 退而抓第一个 `{` 到最后一个 `}` 之间内容
3. 最后尝试原始字符串

### 9.4 LLM 不稳定性的三层兜底

| 层 | 函数 | 作用 |
|----|------|------|
| 解析层 | `_parse_llm_output` | 从 markdown 中抽 JSON |
| 后处理 | `_post_process_dsl` | 字段补全（缺 func/field 时反查） |
| 语义兜底 | `_semantic_fix_dsl` | filter（地区/渠道/客户类型）和 limit（top-N）硬性兜底 |

**注意**：metrics/dimensions 的语义识别**完全交给 LLM + RAG**，代码层不再写关键词列表。

---

## 10. LangGraph 工作流

### 10.1 主图节点

```
START → clarification → validation(子图) → permission_check(子图)
      → resolve_semantic → build_sql → scan_sql → sandbox_check
      → [pass]   execute_sql → [success] END
      → [risk]   human_review → [approved] execute_sql
      → [fail]   simplify_dsl → build_sql (重试)
```

### 10.2 子图

**validation 子图**：

```
generate_dsl (RAG + LLM) → validate_dsl
            ↓ fail            ↓ ok → END
        mock_dsl (fallback)
            ↓
        validate_dsl → [retry < 3] → correct_dsl → validate_dsl
```

**permission_check 子图**：

```
inject_row_permission → check_col_permission → END
```

### 10.3 Checkpointer + 中断

`InMemorySaver` 让流程可中断、可恢复。`sandbox_check` 发现风险时通过 `interrupt_before=["human_review"]` 中断，等待人工调用 `/api/v1/query/resume` 继续。

---

## 11. 多数据库适配

### 11.1 支持数据库

* SQLite（默认）
* MySQL
* PostgreSQL
* ClickHouse
* Doris
* Hive / SparkSQL / Trino

### 11.2 方言适配

通过 `sqlglot.transpile(sql, source, dialect)` 转换，处理：

* LIMIT / OFFSET 差异
* 时间函数差异
* JSON 函数差异
* 聚合函数差异

---

## 12. 安全设计

### 12.1 SQL 审计

每次查询记录到 SQLite 审计表：

| 字段 | 内容 |
|------|------|
| query_id | UUID |
| user_id / tenant_id | 来源用户 |
| question | 用户原始问题 |
| dsl_json | 生成的 DSL |
| sql_text | 最终执行的 SQL |
| status | success / error / clarification / pending_review |
| execution_time_ms | 总耗时 |
| trace_json | 每个节点的输入输出 |
| error_code / error_message | 失败时的错误码 |

支持 `INSERT OR REPLACE` 避免重复记录冲突。

### 12.2 敏感字段控制

禁止访问（`configs/permissions.yaml`）：

* salary
* phone
* id_card
* email

### 12.3 沙箱预检

执行前用 `EXPLAIN QUERY PLAN` + `LIMIT 10` 预览：

* 估算扫描行数（超阈值标记风险）
* 实际执行延迟（超阈值标记风险）
* 触发风险时中断进入 `human_review`

---

## 13. 反馈闭环

### 13.1 错误沉淀

`/api/v1/feedback` 接收用户标注：

* 用户问题
* 系统生成的 DSL
* 用户修正后的 DSL

写入 `feedback.jsonl` + 审计日志。

### 13.2 未来：自动学习

用户标注的"正确 DSL"自动 upsert 到 `history` 集合 → 下次同类问题 RAG 直接命中。

---

## 14. 技术栈（当前实现）

| 模块 | 技术 |
|------|------|
| LLM | GLM-4.5-Air / Qwen / 任意 OpenAI 兼容接口 |
| DSL 校验 | Pydantic v2 |
| Query Pipeline | LangGraph StateGraph |
| Query Compiler | SQLAlchemy Core + sqlglot |
| Semantic Layer | YAML + 自实现 Registry |
| Warehouse | SQLite（生产可切 MySQL/PostgreSQL/ClickHouse） |
| Vector DB | Milvus Lite |
| Embedder | BGE-base-zh-v1.5 |
| API | FastAPI |
| Workflow | LangGraph |
| 前端 | React + Vite + AntD + ECharts + Playwright |

---

## 15. 执行链路

```
User
 → API
 → LangGraph StateGraph:
     clarification
     → validation 子图 (RAG → LLM → 校验 → 修正循环)
     → permission_check 子图 (行级注入 + 列级检查)
     → resolve_semantic
     → build_sql
     → scan_sql
     → sandbox_check
     → [risk] human_review (中断)
     → execute_sql
     → [fail] simplify_dsl (重试)
 → Audit Logger
 → Response
```

---

## 16. 与传统 NL2SQL 对比

| 能力 | 传统 NL2SQL | NL2DSL（本系统） |
|------|----------|----------------|
| SQL 可控性 | 差 | 强 |
| 权限治理 | 弱 | 强 |
| Query 优化 | 基本没有 | 较完整支持 |
| 多数据库适配 | 困难 | 简单（sqlglot） |
| 可调试性 | 差 | 强（debug RAG / trace 链路） |
| LLM 不稳定容错 | 差 | 三层兜底 |
| 配置驱动 | 无 | YAML + 启动自检 |
| 企业落地 | 困难 | 可生产化 |

---

## 17. 总结

企业级智能问数系统的核心：

不是：

```
自然语言 -> SQL
```

而是：

```
自然语言
 -> RAG（业务知识检索）
 -> Semantic DSL
 -> Validator + Permission
 -> SQL Compiler
 -> Sandbox
 -> Execution
 -> Audit
```

本质上：

**AI 负责语义理解**（什么意思）

**RAG 负责业务记忆**（"流水"=gmv、"客单价"=AOV）

**System 负责执行治理**（校验、权限、审计、优化）

**数据库负责执行**

最终实现：

* 可治理
* 可审计
* 可优化
* 可扩展
* 配置驱动
* 可生产化

的企业级 AI Query Engine。
