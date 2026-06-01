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
