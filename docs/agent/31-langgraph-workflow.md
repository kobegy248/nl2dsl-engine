# 31. LangGraph 工作流与链路追踪

## 31.1 工作流

```
START
  ↓
clarification — 歧义检测，有歧义直接返回
  ↓
decompose — 复杂查询改写（对比/同比/趋势 → 单 DSL）
  ↓
RAG 检索 — 召回 schema/metrics/terms/history（含 join 关系）
  ↓
generate_dsl — LLM 生成初始 DSL
  ↓
validate_dsl — 结构校验
  ↓
校验通过？
  ├─ 通过 → permission_check
  ├─ 不通过 → correct_dsl（Agentic：LLM 决策检索词 → 定向 RAG → 重生成）
  │              ↓
  │           validate_dsl（重试，最多 3 次）
  └─ 修正失败 → 返回错误
  ↓
permission_check — 行级注入 + 列级检查
  ↓
resolve_semantic — 指标展开
  ↓
build_sql — SQLAlchemy Core 构建
  ↓
scan_sql — 安全扫描
  ↓
sandbox_check — EXPLAIN 预检
  ↓
通过？
  ├─ 风险 → human_review（中断等待人工确认）
  └─ 通过 → execute_sql
  ↓
execute_sql — 数据库执行，并按 DSL 配置执行分组 TopN / 占比后处理
  ↓
成功？
  ├─ 失败 → simplify_dsl → build_sql（重试）
  └─ 成功 → verify_dsl
  ↓
verify_dsl — LLM 自检（PASS/WARN/FAIL，warning-only）
  ↓
审计日志 — 记录完整 trace 链路
  ↓
返回结果
```

## 31.2 调用链路追踪

每次查询必须生成完整的调用链路，记录每个处理节点的输入、输出、耗时和状态。

**链路节点定义：**

| 节点 | 输入 | 输出 | 失败时阻断后续 | Agentic |
|------|------|------|--------------|---------|
| `clarification` | 用户问题 | 歧义列表 / None | 是（有歧义直接返回） | 否 |
| `decompose` | 用户问题 | 改写后的问题 / 原问题 | 否 | **是** |
| `rag_retrieve` | 子查询 | 检索到的上下文片段 | 否（可降级为空上下文） | 否 |
| `generate_dsl` | 问题 + RAG context | 原始 DSL (JSON) | 是 | RAG |
| `validate_dsl` | DSL 对象 | 校验结果 | 是 | 否 |
| `correct_dsl` | 错误 + 上次 DSL | 修正后的 DSL | 否（失败进入 mock） | **是** |
| `permission_inject` | DSL + 用户信息 | 注入权限后的 DSL | 是 | 否 |
| `semantic_resolve` | DSL | 展开指标后的 DSL | 是 | 否 |
| `build_sql` | DSL | 标准 SQL | 是 | 否 |
| `scan_sql` | 标准 SQL | 扫描结果 | 是 | 否 |
| `sandbox_check` | SQL + DB | 沙箱结果 | 是 | 否 |
| `execute_sql` | SQL + DSL.post_process | 查询结果 / 高级分析结果 | 是 | 否 |
| `verify_dsl` | DSL + 结果 + 原问题 | PASS/WARN/FAIL | 否（warning-only） | **是** |
| `audit_log` | 完整链路 | 日志记录 | 否 | 否 |

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
