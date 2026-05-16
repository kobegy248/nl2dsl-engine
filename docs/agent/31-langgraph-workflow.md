# 31. LangGraph 工作流与链路追踪

## 31.1 工作流

```
START
  ↓
意图识别 — 理解用户意图、识别计算类型（查询/对比/趋势）
  ↓
查询拆分 — 将多意图问题拆分为独立子查询
  ↓
RAG 检索 — 为每个子查询召回相关表结构、指标、示例
  ↓
LLM 生成 DSL — 根据上下文生成初始 DSL
  ↓
DSL 自检 — LLM 检查 DSL 合理性（字段是否存在、逻辑是否通顺）
  ↓
校验通过？
  ├─ 通过 → 权限注入
  ├─ 不通过 → 修正重试（最多 3 次）
  └─ 修正失败 → 返回错误
  ↓
权限注入 — 自动注入行级/列级权限
  ↓
Query Planner — 优化、Join 推导
  ↓
SQL 生成与执行
  ↓
结果合并 — 多子查询结果合并/对比计算
  ↓
审计日志 — 记录查询全过程
  ↓
返回结果
```

## 31.2 调用链路追踪

每次查询必须生成完整的调用链路，记录每个处理节点的输入、输出、耗时和状态。

**链路节点定义：**

| 节点 | 输入 | 输出 | 失败时阻断后续 |
|------|------|------|--------------|
| `intent_parse` | 用户问题 | 意图类型（查询/对比/趋势/多子查询） | 否（可降级为简单查询） |
| `query_split` | 用户问题 + 意图 | 子查询列表 | 否（无法拆分则作为单查询） |
| `rag_retrieve` | 子查询 | 检索到的上下文片段 | 否（可降级为空上下文） |
| `llm_generate` | 子查询 + 上下文 | 原始 DSL (JSON) | 是 |
| `dsl_parse` | 原始 DSL | 解析后的 DSL 对象 | 是 |
| `dsl_validate` | DSL 对象 | 校验结果 | 是 |
| `permission_inject` | DSL + 用户信息 | 注入权限后的 DSL | 是 |
| `semantic_resolve` | DSL | 展开指标后的 DSL | 是 |
| `query_plan` | DSL | 优化后的执行计划 | 是 |
| `sql_build` | 执行计划 | 标准 SQL | 是 |
| `dialect_convert` | 标准 SQL | 方言 SQL | 是 |
| `sql_scan` | 方言 SQL | 扫描结果 | 是 |
| `sql_execute` | 方言 SQL | 查询结果 | 是 |
| `result_merge` | 多子查询结果 | 合并后的最终结果 | 否 |
| `result_mask` | 查询结果 | 脱敏后的结果 | 否 |
| `audit_log` | 完整链路 | 日志记录 | 否 |

**链路记录格式：**

```json
{
  "query_id": "uuid",
  "trace": [
    {
      "node": "llm_generate",
      "status": "success",
      "input": {"question": "查询华东地区销售额", "context": "..."},
      "output": {"dsl": {"metrics": [...], "dimensions": [...]}},
      "duration_ms": 1250,
      "timestamp": "2024-05-16T10:00:01Z"
    },
    {
      "node": "dsl_validate",
      "status": "error",
      "input": {"dsl": {"metrics": [{"field": "sale_amount"}]}},
      "output": {"error": "字段 'sale_amount' 不存在，是否指 'sales_amount'?"},
      "duration_ms": 5,
      "timestamp": "2024-05-16T10:00:02Z"
    }
  ],
  "total_duration_ms": 1255
}
```

## 31.3 错误回溯机制

查询失败时，根据链路记录快速定位问题根因：

| 错误节点 | 可能原因 | 回溯方向 |
|---------|---------|---------|
| `llm_generate` | LLM 幻觉、Prompt 不足、RAG 上下文缺失 | 检查 RAG 召回内容、LLM 原始输出 |
| `dsl_validate` | 字段拼写错误、指标未注册 | 检查 DSL 中的字段名、语义层配置 |
| `permission_inject` | 权限配置错误 | 检查用户权限配置、敏感字段规则 |
| `sql_execute` | SQL 语法错误、数据库连接问题 | 检查生成的 SQL、数据库状态 |

**回溯示例：**

用户反馈"查销售额报错"，通过 `query_id` 查询链路：

```
query_id: abc-123
  └─ llm_generate: success (output: dsl={"metric": "sale_amount"})
  └─ dsl_validate: error (field 'sale_amount' not found)
```

根因：LLM 拼写错误，`sale_amount` → 应为 `sales_amount`。

**存储：**

链路数据与审计日志存储在同一张表（或关联表），通过 `query_id` 关联。保留周期 30 天（可配置）。

审计日志表结构（SQLite）：

```sql
CREATE TABLE nl2dsl_audit_log (
    query_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    question TEXT NOT NULL,
    dsl_json TEXT,
    sql_text TEXT,
    status TEXT NOT NULL,
    execution_time_ms INTEGER,
    rows_scanned INTEGER,
    rows_returned INTEGER,
    trace_json TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_user_time ON nl2dsl_audit_log(user_id, created_at);
CREATE INDEX idx_tenant_time ON nl2dsl_audit_log(tenant_id, created_at);
```
