# 审计日志设计

## 设计目标

记录每次查询的完整生命周期，实现**操作可追溯、问题可排查、性能可分析**。

## 数据模型

### 数据库表结构

```sql
CREATE TABLE nl2dsl_audit_log (
    query_id        TEXT PRIMARY KEY,       -- UUID，唯一标识每次查询
    user_id         TEXT NOT NULL,          -- 发起查询的用户
    tenant_id       TEXT DEFAULT '',        -- 租户ID（多租户隔离）
    question        TEXT NOT NULL,          -- 用户的自然语言问题
    dsl_json        TEXT,                   -- 生成的 DSL（JSON格式）
    sql_text        TEXT,                   -- 生成的 SQL
    status          TEXT NOT NULL,          -- success / error / clarification
    execution_time_ms INTEGER,              -- 总执行耗时（毫秒）
    rows_scanned    INTEGER,                -- 扫描行数
    rows_returned   INTEGER,                -- 返回行数
    trace_json      TEXT,                   -- 链路追踪（JSON数组）
    error_code      TEXT,                   -- 错误码（如有）
    error_message   TEXT,                   -- 错误信息（如有）
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## API 接口

### 查询单条记录详情

```
GET /api/v1/admin/audit/queries/{query_id}
```

返回完整的审计记录，含 DSL、SQL、Trace 解码后的结构化数据。

### 列表查询

```
GET /api/v1/admin/audit/queries
  ?user_id=xxx        -- 按用户过滤
  &tenant_id=xxx      -- 按租户过滤
  &status=error       -- 按状态过滤
  &start_time=...     -- 时间范围开始
  &end_time=...       -- 时间范围结束
  &q=关键词            -- 问题内容模糊搜索
  &limit=20           -- 分页限制（1-100）
  &offset=0           -- 分页偏移
```

返回：
```json
{
  "status": "success",
  "total": 150,
  "limit": 20,
  "offset": 0,
  "items": [...]
}
```

## 写入机制

审计日志采用 **UPSERT** 机制：

1. 查询开始时写入初始记录（仅 query_id、user_id、question、status="pending"）
2. 查询完成后更新同一条记录（补充 dsl_json、sql_text、status、execution_time_ms 等）
3. 异常时也能保留已收集的字段，避免信息丢失

```python
# 首次写入（查询开始时）
audit_logger.log(query_id=..., user_id=..., question=..., status="pending")

# 二次更新（查询完成时）
audit_logger.log(query_id=..., dsl_json=..., sql_text=..., status="success")
```

## 保留策略

当前使用 SQLite 存储，生产环境建议：

| 环境 | 存储 | 保留策略 |
|------|------|---------|
| 开发 | SQLite | 无限制 |
| 测试 | SQLite | 每次测试前清理 |
| 生产 | PostgreSQL | 热数据 90 天 + 冷数据归档 |

## 隐私合规

- `dsl_json` 和 `sql_text` 包含查询内容，访问需权限控制
- 管理接口 `/api/v1/admin/audit/*` 应增加管理员鉴权
- 考虑对敏感字段（如用户输入中的个人信息）进行脱敏存储

## 第五周：query_id 透出与反馈关联

### query_id 透出

以下响应均新增 `query_id` 字段（向后兼容的可选字段）：

- `POST /api/v1/query` → `QueryResponse.query_id`
- `POST /api/v1/query/dsl` → `DSLGenerateResponse.query_id`
- `POST /api/v1/query/execute` → `DSLExecuteResponse.query_id`
- `POST /api/v1/query/stream` 的 SSE 最终 `result` 与 `done` 事件 `data.query_id`

用户可直接用响应中的 `query_id` 提交反馈，无需猜测。

### Query ID 与 Audit 的完整关联（修复）

`/query`、`/query/dsl`、`/query/execute` 的成功 / 失败 / 澄清结果，以及 `/query/stream`
的 SSE 最终结果，**均**按现有审计契约写入审计日志，且使用响应中的同一个 `query_id`
（至少记录 user_id、tenant_id、状态、DSL、SQL、耗时、Trace、错误信息）。因此
`query_id` 可直接用于 `GET /api/v1/admin/audit/queries/{query_id}` 查询审计详情，
并用于提交反馈。此前 `/query/execute` 生成 query_id 但不写审计、SSE 只发空 done 事件
的问题已修复。

### 管理 API 的租户边界（修复）

`GET /api/v1/admin/audit/queries` 列表接口必须通过 `tenant_id` 查询参数限定租户范围；
未提供返回 `400`，禁止未限定租户的全量查询。

**单条详情接口同样强制租户隔离（第二轮审阅 P0）**：
`GET /api/v1/admin/audit/queries/{query_id}` 必须提供非空 `tenant_id` 查询参数，
未提供或空白返回 `400`。租户校验下沉到 `AuditLogger.get_query(query_id, tenant_id=...)`，
在 SQL 层直接 `AND tenant_id = :tenant_id` 过滤；记录不存在或属于其他租户统一返回
`404`，不泄露记录是否存在。项目尚无认证框架，当前以强制 `tenant_id` 过滤为底线，
后续接入正式认证授权后应以调用方身份收敛。

### Web 端 tenant_id 数据来源（第三轮审阅 P1）

前端审计列表 / 详情请求必须携带非空 `tenant_id`，否则后端返回 `400`。为避免在多个
文件硬编码，Web 端统一由 `TenantContext`（`web/src/context/TenantContext.tsx`）提供
`tenantId` 与 `ready`：

- `useAuditList` / `useAuditDetail` 从 `useTenant()` 取 `tenantId`，列表与详情的
  `queryKey` 均包含 `tenantId`，避免跨租户缓存污染。
- `ready` 为假（`tenantId` 为空）时查询 `disabled`，不发请求，规避后端 400。
- 切换 `tenantId` 后 `queryKey` 变化，自动发起新请求，不复用其他租户缓存。
- 项目接入正式身份后只需替换 `TenantContext` 实现，调用方无需改动。Feedback 管理前端
  同样从该上下文取租户，复用同一来源。

### 与 Feedback 共库

`nl2dsl_feedback` 表与 `nl2dsl_audit_log` 共用同一 SQLAlchemy Engine。反馈写入前
通过 `AuditLogger.get_query(query_id)` 校验审计记录存在且 user / tenant 匹配。应用
层校验，不依赖数据库外键。

### 质量报告聚合

`nl2dsl.quality` 模块从审计日志统计：

- 查询总数与状态分布（success / warning / clarification / error）。
- P50 / P95 延迟。
- 按路径的 Trace 完整率。各路径及其最小节点集合：
  - **success**：`generate_dsl / validate_dsl / resolve_semantic / build_sql /
    scan_sql / execute_sql`。
  - **success_with_optimizer**：上述节点 + `optimize_dsl`。
  - **clarification**：`clarification` 节点。
  - **agent**（复杂查询）：`agent` 节点 + 至少一条子查询执行证据
   （`build_sql / execute_sql / scan_sql / sub_query / sub_query_start / sub_query_end`
   之一），单 agent 节点不计完整。识别的步骤名与 `AgentOrchestrator` 实际生产的
   Trace 一致（见下节），不维护一套永远不会生成的名称。
  - **error**：非空 Trace 即计完整（错误可发生在任意步骤）。
  - **unknown**：无法识别的路径，**默认计为不完整**；空 Trace 一律不完整。
- 报告同时给出各路径的总数 / 完整数 / 完整率，便于定位 Trace 缺失集中在哪条路径。
- dsl / sql / trace 字段完整率。

### Agent Trace 最小完整路径（第二轮审阅 P1）

复杂查询（`/query` 复杂路径与复杂 SSE）的审计 Trace 由 `AgentOrchestrator` 真实生产，
至少体现以下核心步骤：

```text
agent（编排开始）
  └─ plan（意图分解：intent + sub_query_count）
       ├─ sub_query_start（每个子查询开始）
       ├─ sub_query_end（每个子查询执行状态：success / error）
       └─ aggregation（聚合；全部子查询被阻断时为 skipped）
            └─ explanation（自然语言解释）
```

- `sub_query_end` 携带子查询执行状态，是质量分析器认定的“子查询执行证据”。
- 某个子查询失败时 Trace 体现 `sub_query_end status=error`，审计状态为 error/warning，
  **不伪装为完整成功**。
- 普通复杂查询与复杂 SSE 的 Trace 核心步骤一致（`agent` + 子查询证据）。
- `AgentOrchestrator.run` 在实体抽取 / 路由 / 分发各阶段抛异常时，Trace 记录对应
  error 步骤并随 `AgentResult.trace` 写入审计。
