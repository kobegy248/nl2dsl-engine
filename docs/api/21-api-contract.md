# 21. API 契约

## 21.1 核心接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/query` | POST | 自然语言查询，完整链路执行 |
| `/api/v1/query/dsl` | POST | 只生成 DSL 和 SQL，不执行 |
| `/api/v1/query/execute` | POST | 直接执行给定的 DSL |

**Request 示例：**
```json
{
  "question": "查询华东地区 2024Q1 销售额最高的 10 个产品",
  "domain": "ecommerce",
  "user_id": "u123",
  "tenant_id": "t001"
}
```

`domain` 字段可选，默认为 `"ecommerce"`。Engine 自动发现 configs/ 目录下的所有域（如 `bank_metrics.yaml` → `"bank"`），每个域有独立的 DB + Milvus + RAG。

**Response 示例：**
```json
{
  "status": "success",
  "query_id": "uuid",
  "data": [{"product_name": "产品A", "sales_amount": 150000}],
  "dsl": {...},
  "sql": "SELECT ...",
  "execution_time_ms": 150,
  "rows_scanned": 10000
}
```

`query_id`（第五周新增，向后兼容的可选字段）在 `/api/v1/query`、
`/api/v1/query/dsl`、`/api/v1/query/execute` 的响应，以及 `/api/v1/query/stream`
SSE 最终 `result` / `done` 事件中均会返回，用于反馈关联。

> **Query ID 与 Audit 的完整关联（修复）**：`/query`、`/query/dsl`、`/query/execute`
> 的成功 / 失败 / 澄清结果，以及 `/query/stream` 的 SSE 最终结果，均按现有审计契约
> 写入审计日志，且使用响应中的同一个 `query_id`。因此 `query_id` 可直接用于查询审计
> 详情（`/api/v1/admin/audit/queries/{query_id}`）和提交反馈。未知 `domain` 立即
> 返回 `404`，不静默回退 `ecommerce`。

### 查询状态与数据可用性

| `status` | 数据是否可用 | 契约 |
|----------|--------------|------|
| `success` | 是 | 查询成功，返回实际的 `data`、`dsl`、`sql` 和解释信息 |
| `warning` | 是 | SQL 已成功执行，但存在非阻断警告；必须保留实际 `data`，客户端应展示结果并提示用户核对口径 |
| `pending_review` | 否 | 查询需要人工审核，`data` 为空，不应作为可用结果展示 |
| `clarification` | 否 | 查询存在歧义，需要用户补充信息 |
| `error` | 否 | 查询执行失败，按错误响应契约返回 |

`warning` 表示“结果可用但需关注”，不能因为优化器、置信度或语义检查产生警告而丢弃已经成功执行的查询结果。

## 21.2 管理接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/schema` | GET | 获取语义层 Schema（`?domain=` 可选，默认 ecommerce） |
| `/api/v1/metrics` | GET | 获取指标列表（`?domain=` 可选） |
| `/api/v1/feedback` | POST | 提交 DSL 纠错反馈（校验审计关联 + 去重） |
| `/api/v1/admin/feedback` | GET | 反馈列表（含审计摘要，支持 user/tenant/query_id/status 过滤） |
| `/api/v1/admin/feedback/{feedback_id}` | GET | 反馈详情（含关联审计摘要） |
| `/api/v1/admin/audit/queries` | GET | 审计查询列表（按 tenant/user/status/时间窗口/问题模糊匹配过滤） |
| `/api/v1/admin/audit/queries/{query_id}` | GET | 审计查询详情（含 DSL/SQL/Trace） |

### FeedbackRequest（统一契约，第五周）

```json
{
  "query_id": "uuid",
  "user_id": "u001",
  "tenant_id": "t001",
  "is_correct": false,
  "issue_type": "metric",
  "corrected_dsl": {},
  "comment": "销售额口径不正确"
}
```

- `query_id` 必须对应已存在的审计记录，且 `user_id` / `tenant_id` 与审计一致。
- **`tenant_id` 必填且不得为空白（强校验，修复）**：缺失或全空格返回 `422`；
  `FeedbackStore` 在 Store 层亦做防御性非空校验，不依赖 API 层。审计记录有
  `tenant_id` 时，请求 `tenant_id` 缺失 / 为空 / 不一致一律拒绝（`400`），
  不返回其他租户的审计内容。
- `corrected_dsl` 存在时通过 DSL Schema 校验。
- 至少提供 `is_correct=false` / `corrected_dsl` / 非空 `comment` 之一。
- `issue_type` 枚举：`intent / metric / dimension / filter / time / join / ranking /
  proportion / permission / result / other`。

**Response：**
```json
{
  "status": "received",
  "query_id": "uuid",
  "feedback_id": "fb-xxxx",
  "deduplicated": false
}
```

重复提交（相同 `dedup_hash`）返回原 `feedback_id`，`deduplicated=true`。去重基于
`dedup_hash` 的 UNIQUE 约束原子完成，并发竞争时捕获约束冲突并回查原 ID，不会抛 500。

### 管理 API 的租户边界（修复）

`/api/v1/admin/feedback` 与 `/api/v1/admin/audit/queries` 列表接口**必须**通过
`tenant_id` 查询参数限定租户范围；未提供 `tenant_id` 返回 `400`，禁止未限定租户的
全量查询。项目尚无认证框架，当前以强制 `tenant_id` 过滤为底线，剩余的调用方身份
认证风险见 `docs/audit/audit-log-design.md`。

### 详情接口的租户隔离（第二轮审阅 P0）

`/api/v1/admin/feedback/{feedback_id}` 与 `/api/v1/admin/audit/queries/{query_id}`
详情接口**同样必须**提供非空 `tenant_id` 查询参数，与列表接口保持一致的租户边界：

- 未提供或空白 `tenant_id` → `400 VALIDATION_ERROR`。
- 租户校验**下沉到 Store / Logger 查询方法**：`FeedbackStore.get(feedback_id, tenant_id=...)`
  与 `AuditLogger.get_query(query_id, tenant_id=...)` 在 SQL 层直接加上
  `AND tenant_id = :tenant_id` 过滤，避免 API 层先取出跨租户数据再判断。
- 记录不存在或属于其他租户，统一返回 `404`，**不泄露记录是否存在**。
- 响应不得包含其他租户的 SQL / DSL / Trace / 问题文本 / 反馈内容。

示例：

```
GET /api/v1/admin/audit/queries/{query_id}?tenant_id=t001
GET /api/v1/admin/feedback/{feedback_id}?tenant_id=t001
```

## 21.2.1 `/api/v1/query/execute` 失败审计与错误响应（第二轮审阅 P1）

`/query/execute` 用统一的 `try/except/finally` 覆盖整个执行流程（领域解析 → DSL
解析 → graph 执行 → SQL 构建/扫描/执行），确保成功 / clarification / 业务错误 /
未预期异常都写入同一条 `query_id` 对应的审计记录（使用现有 UPSERT）。

失败时响应体携带 `query_id`，便于客户端关联审计与提交反馈：

```json
{
  "status": "error",
  "error_code": "DSL_SCHEMA_ERROR | NOT_FOUND | VALIDATION_ERROR | INTERNAL_ERROR",
  "message": "安全化的错误信息（抹除密钥/连接串）",
  "query_id": "uuid"
}
```

- DSL Schema 解析失败（pydantic 校验）→ `422`，`error_code=DSL_SCHEMA_ERROR`。
- 未知 `domain`（`_get_domain_graph` 抛 `NotFoundError`）→ `404`，`error_code=NOT_FOUND`。
- graph 返回 `error` 状态 / SQL 构建/执行失败 → `400`，`error_code=VALIDATION_ERROR`。
- 其它未预期异常 → `500`，`error_code=INTERNAL_ERROR`，信息经 `_safe_error_message`
  抹除 `user:pass@` / `password=` / `api_key=` 等凭据模式后截断。
- 成功 → `200`，响应含 `query_id`（与审计记录一致，仅此一条）。

## 21.2.2 `/api/v1/query/stream` SSE 事件格式（第二轮审阅 P1）

简单查询（single_query）流式端点的事件契约：

- `update`：每个 graph 节点的更新块（`stream_mode="updates"`），原样透传。
- `result`：流结束后的**真实最终状态**事件，至少包含：
  ```json
  {
    "query_id": "uuid",
    "status": "success | warning | clarification | error",
    "dsl": {...},
    "sql": "SELECT ...",
    "data": [...],
    "rows_returned": 10,
    "error": "失败时的错误信息",
    "error_code": "..."
  }
  ```
  最终状态由**合并所有 update chunk** 得到（`_merge_update_chunks`），**不**把最后一个
  update chunk 当作完整状态。`trace` 字段累加去重。
- `error`：`astream()` 抛异常时输出的结构化错误事件，含 `query_id` / `error` /
  `error_code`，随后写 `error` 审计并正常结束流（不吞异常伪装 success）。
- `done`：流终止事件，携带 `query_id`。

成功 / clarification / 失败均按真实最终状态写入审计（同一 `query_id`）。复杂查询
SSE 走 `AgentOrchestrator`，`result` 事件额外携带 `trace`（见下节 Agent Trace）。

### 正式 App 的唯一创建方式

正式生产入口 `nl2dsl/api.py` 为薄封装，仅调用
`nl2dsl.api_factory.create_app()` 构建正式 app。`uvicorn nl2dsl.api:app` 与测试创建
的 app 走同一实现，不再维护两套路由 / 请求模型 / 反馈逻辑。`create_app()` 无覆盖参数
时走生产路径，复用 `Engine` 真实 `DomainContext`（含 RAG / Optimizer / 权限 / 审计 /
数据库 `FeedbackStore`）；传入 `registry_dict` / `engine` 等覆盖项时走测试注入路径。

## 21.3 枚举管理接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/admin/enums` | GET | 查询所有枚举映射 |
| `/api/v1/admin/enums` | POST | 新增映射 |
| `/api/v1/admin/enums/{id}` | PUT | 修改映射 |
| `/api/v1/admin/enums/refresh` | POST | 热更新缓存 |
