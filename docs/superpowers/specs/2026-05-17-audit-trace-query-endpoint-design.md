# 历史查询链路查询接口 - 设计文档

**日期**: 2026-05-17
**作者**: brainstorming via /superpowers:brainstorming
**状态**: 待审阅

## 1. 背景

`/api/v1/query` 在执行时已经把每次自然语言查询的完整链路写入 `nl2dsl_audit_log.trace_json`(见前置改动)。但目前只能直接 `sqlite3` 进数据库手工查询,缺一个可被外部消费(运维面板 / Postman / curl)的 HTTP 接口。

需求要点:
- 通过 HTTP 接口查询历史的"自然语言 -> DSL -> SQL -> 数据"完整链路
- **保持原有代码架构不变** —— 不引入新的包/模块/分层
- **兼容旧逻辑** —— 老的 `trace_json` 为 NULL 的记录依然能正常返回

## 2. 目标 / 非目标

### 2.1 目标
- 通过 query_id 取单条审计记录的完整链路(DSL、SQL、trace、产物)
- 通过多维过滤列出历史查询(user/tenant/status/时间窗口/问题模糊匹配 + 分页)
- 与现有 API 风格、错误响应、URL 前缀保持一致
- 兼容老数据(trace_json 为 NULL 时也正确返回)

### 2.2 非目标
- 不做用户身份认证 / 鉴权(项目本身就还没有 auth 层)
- 不做实时推送(WebSocket / SSE)
- 不做导出 / 报表(只读取)
- 不重构 AuditLogger 或审计表 schema
- 不接入 LLM 真链路审计(`llm/agent.py` 的 audit 也没传 trace,留作后续单独修)

## 3. 接口契约

### 3.1 列表
```
GET /api/v1/admin/audit/queries
```

查询参数(全部可选):

| 参数 | 类型 | 说明 |
|------|------|------|
| `user_id` | string | 精确匹配 |
| `tenant_id` | string | 精确匹配 |
| `status` | `success` \| `error` | 精确匹配 |
| `start_time` | ISO 8601 string | `created_at >= start_time` |
| `end_time` | ISO 8601 string | `created_at <= end_time` |
| `q` | string | 在 `question` 字段做 `LIKE '%...%'` 匹配 |
| `limit` | int | 默认 20,最大 100,超过即报 400 |
| `offset` | int | 默认 0 |

响应 200:
```json
{
  "status": "success",
  "total": 137,
  "limit": 20,
  "offset": 0,
  "items": [
    {
      "query_id": "b64e2b3d-b57c-4507-91b1-28ff7204690c",
      "user_id": "u001",
      "tenant_id": "t001",
      "question": "查询华东地区销售额最高的 10 个产品",
      "status": "success",
      "execution_time_ms": 20,
      "rows_returned": 10,
      "error_code": null,
      "created_at": "2026-05-17 12:27:21"
    }
  ]
}
```

排序:`created_at DESC, query_id DESC` (作为稳定的二级排序)

**列表中不返回**:`dsl_json` / `sql_text` / `trace_json` / `error_message` — 这些是大字段,放详情接口里。

### 3.2 详情
```
GET /api/v1/admin/audit/queries/{query_id}
```

响应 200:
```json
{
  "status": "success",
  "item": {
    "query_id": "...",
    "user_id": "u001",
    "tenant_id": "t001",
    "question": "查询华东地区销售额最高的 10 个产品",
    "dsl": { "metrics": [...], "filters": [...], "...": "..." },
    "sql": "SELECT ...",
    "status": "success",
    "execution_time_ms": 20,
    "rows_scanned": null,
    "rows_returned": 10,
    "trace": [
      {
        "step": "dsl_generate",
        "status": "success",
        "duration_ms": 0,
        "output": { "dsl": { "...": "..." } }
      },
      { "step": "validate", "status": "success", "duration_ms": 0 },
      "..."
    ],
    "error_code": null,
    "error_message": null,
    "created_at": "2026-05-17 12:27:21"
  }
}
```

**字段映射说明**:
- 数据库列 `dsl_json` / `sql_text` / `trace_json` 在响应里改名为 `dsl` / `sql` / `trace`,且解析为 JSON(而不是 string)
- 老记录 `trace_json` 为 NULL 时,响应里 `trace` 返回 `[]`
- 老记录 `dsl_json` 为 NULL 时(error 分支),响应里 `dsl` 返回 `null`

不存在时 404:
```json
{
  "status": "error",
  "error_code": "NOT_FOUND",
  "message": "audit record not found: query_id=xxx"
}
```

参数校验失败 400:
```json
{
  "status": "error",
  "error_code": "VALIDATION_ERROR",
  "message": "limit must be between 1 and 100"
}
```

## 4. 实现结构(架构不变)

### 4.1 文件改动清单

| 文件 | 改动 | 说明 |
|------|------|------|
| `nl2dsl/audit/logger.py` | 在 `AuditLogger` 上新增 2 个方法 | 不动现有 `log()` / `query(sql)` |
| `nl2dsl/api.py` | 加 2 个路由 + 请求/响应 Pydantic 模型 | 模块级 `_audit_logger` 已存在 |
| `nl2dsl/api_factory.py` | 加同样的 2 个路由(`create_app` 内) | 给测试用 |
| `nl2dsl/exceptions.py` | 新增 `NotFoundError`(若不存在) | 与现有 `ValidationError` 等同层 |
| `tests/e2e/test_audit_query_api.py` | 新增 | TDD 用 |

### 4.2 `AuditLogger` 新增方法签名

```python
class AuditLogger:
    # 现有方法不变: __init__, _ensure_table, log, query

    def list_queries(
        self,
        *,
        user_id: str | None = None,
        tenant_id: str | None = None,
        status: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        question_like: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """返回 (items, total)。items 不包含大字段。"""

    def get_query(self, query_id: str) -> dict | None:
        """返回单条审计记录(包含 dsl/sql/trace 已解析为 JSON);不存在返回 None。"""
```

**实现要点**:
- SQL 使用参数化(`text(...).bindparams(...)`),禁止字符串拼接
- `dsl_json` / `trace_json` 字段在 `get_query` 内直接 `json.loads()` 后返回(空字符串 / NULL 当作 `[]` / `None`)
- `list_queries` 通过两次查询拿 items 和 total(简单可靠,审计量大时可优化但目前 YAGNI)

### 4.3 路由实现(伪代码)

```python
class AuditQueryListItem(BaseModel):
    query_id: str
    user_id: str
    tenant_id: str
    question: str
    status: str
    execution_time_ms: int
    rows_returned: int | None = None
    error_code: str | None = None
    created_at: str

class AuditQueryListResponse(BaseModel):
    status: str = "success"
    total: int
    limit: int
    offset: int
    items: list[AuditQueryListItem]

class AuditQueryDetailItem(BaseModel):
    query_id: str
    user_id: str
    tenant_id: str
    question: str
    dsl: dict | None = None
    sql: str | None = None
    status: str
    execution_time_ms: int
    rows_scanned: int | None = None
    rows_returned: int | None = None
    trace: list[dict] = []
    error_code: str | None = None
    error_message: str | None = None
    created_at: str

class AuditQueryDetailResponse(BaseModel):
    status: str = "success"
    item: AuditQueryDetailItem


@app.get("/api/v1/admin/audit/queries")
async def list_audit_queries(
    user_id: str | None = None,
    tenant_id: str | None = None,
    status_: str | None = Query(None, alias="status"),  # 避开内置名
    start_time: str | None = None,
    end_time: str | None = None,
    q: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> AuditQueryListResponse:
    if not (1 <= limit <= 100):
        raise ValidationError("limit must be between 1 and 100")
    if offset < 0:
        raise ValidationError("offset must be >= 0")
    items, total = _audit_logger.list_queries(
        user_id=user_id, tenant_id=tenant_id, status=status_,
        start_time=start_time, end_time=end_time,
        question_like=q, limit=limit, offset=offset,
    )
    return AuditQueryListResponse(total=total, limit=limit, offset=offset,
                                   items=[AuditQueryListItem(**r) for r in items])


@app.get("/api/v1/admin/audit/queries/{query_id}")
async def get_audit_query(query_id: str) -> AuditQueryDetailResponse:
    row = _audit_logger.get_query(query_id)
    if row is None:
        raise NotFoundError(f"audit record not found: query_id={query_id}")
    return AuditQueryDetailResponse(item=AuditQueryDetailItem(**row))
```

### 4.4 异常处理
- `NotFoundError` 继承 `NL2DSLException`,`error_code = "NOT_FOUND"`,`status_code = 404`
- 现有的 `@app.exception_handler(NL2DSLException)` 会把它转换成标准错误响应(无需另外加 handler)

## 5. 兼容性

| 场景 | 老行为 | 新行为 |
|------|--------|--------|
| `trace_json` 为 NULL(修复前的老记录) | 字段缺失 | 详情接口 `trace` 字段返回 `[]` |
| `dsl_json` 为 NULL(error 分支) | 字段缺失 | 详情接口 `dsl` 字段返回 `null` |
| 现有 `_audit_logger.log()` 调用方 | — | **不动** |
| 现有 `AuditLogger.query(sql)` 方法 | 单测在用 | **不动** |
| 数据库 schema | — | **不动** |
| 现有 `/api/v1/query` 等接口 | — | **不动** |

## 6. 测试计划(TDD)

新建 `tests/e2e/test_audit_query_api.py`,覆盖:

### 6.1 列表接口
1. 调几次 `/api/v1/query` 制造审计记录,然后调 `GET /admin/audit/queries`,断言:
   - 返回 200,`status == "success"`
   - `items` 中只包含本测试创建的记录(用唯一 sentinel question 过滤)
   - 列表项**不包含** `dsl` / `sql` / `trace` 字段
   - 按时间倒序
2. `?user_id=` 过滤生效
3. `?status=success` 过滤生效
4. `?q=华东` 模糊匹配
5. `?start_time=...&end_time=...` 时间窗口
6. 分页:`limit=1&offset=1` 拿到第二条;`total` 字段反映过滤后总数
7. `limit=0` / `limit=101` / `offset=-1` 返回 400 `VALIDATION_ERROR`

### 6.2 详情接口
1. 已存在的 query_id:返回 200,`trace` 是 list,有 8 个步骤,`dsl`/`sql` 是已解析的 JSON
2. 不存在的 query_id:返回 404 `NOT_FOUND`
3. **老记录兼容**:手动 `INSERT` 一条 `trace_json` 为 NULL 的记录,详情接口 `trace` 返回 `[]`(关键兼容点)
4. **error 记录兼容**:手动 `INSERT` 一条 `dsl_json` 为 NULL 的失败记录,详情接口 `dsl` 返回 `null`

### 6.3 安全(基础)
- `q` 参数包含 `'` 时不应导致 SQL 注入(参数化查询)
- 大长度 `q`(1000+ 字符)被正确处理或返回 400

## 7. YAGNI 边界(明确不做)

- 不加身份认证 / 权限校验(项目其他接口也没有)
- 不加排序参数(固定 `created_at DESC`)
- 不做游标分页(`limit/offset` 够用)
- 不做字段裁剪 `?fields=...`(列表和详情各有固定形状)
- 不做按 `error_code` 聚合统计接口
- 不加 trace 内容的全文检索

## 8. 风险

| 风险 | 缓解 |
|------|------|
| 审计表无索引,查询慢 | 当前主键是 `query_id`,过滤字段无索引。审计量小可接受;后续可加 `CREATE INDEX idx_audit_user_time ON nl2dsl_audit_log(user_id, created_at)` 等。本期不做。 |
| `trace_json` 字段大(嵌套 DSL/SQL 多次),详情响应体大 | 仅在详情接口返回,列表不带;客户端按需调取。 |
| 老记录中 `created_at` 时间戳格式不一致 | SQLite 用 `CURRENT_TIMESTAMP` 默认值,统一是 `YYYY-MM-DD HH:MM:SS` ASCII 字符串。新代码直接透传不解析。 |

## 9. 后续可能的演进(不在本期)

- LLM 真链路(`llm/agent.py`)同样补 `trace_json`
- `/api/v1/query/execute` 当前完全没写审计,补上
- 加索引、按 tenant 分库
- 提供 OpenAPI 文档片段供前端面板消费
