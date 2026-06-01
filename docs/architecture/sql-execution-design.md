# SQL 执行层设计

## 设计目标

将经过校验、权限注入、安全扫描的 SQL 安全高效地执行，返回结构化结果。

## 架构

```
scan_sql（安全扫描通过）
    │
    ▼
sandbox_check（沙箱预检通过）
    │
    ▼
SQLExecutor.execute(sql) ──→ 数据库
    │
    ▼
返回 list[dict] 结果
```

## SQLExecutor

当前实现为轻量级封装，职责单一：

```python
class SQLExecutor:
    def __init__(self, engine: Engine):
        self._engine = engine

    def execute(self, sql: str) -> list[dict]:
        with self._engine.connect() as conn:
            result = conn.execute(text(sql))
            rows = [dict(row._mapping) for row in result]
            return rows
```

### 职责边界

| 职责 | 归属 | 说明 |
|------|------|------|
| SQL 构建 | `sql_engine/builder.py` | SQLAlchemy Core 生成标准 SQL |
| 安全扫描 | `sql_engine/scanner.py` | 正则拦截危险模式 |
| 沙箱预检 | `query/sandbox.py` | EXPLAIN + LIMIT 预览 |
| **执行** | `sql_engine/executor.py` | 本模块：连接 → 执行 → 返回 |
| 方言转换 | `sql_engine/dialect.py` | sqlglot 适配不同数据库 |

## 连接管理

### 当前实现

- 使用 SQLAlchemy `Engine` 连接池
- 每次查询通过 `engine.connect()` 获取连接
- 上下文管理器自动释放连接

### 生产环境建议

| 环境 | 连接池配置 |
|------|-----------|
| 开发（SQLite） | 默认单连接 |
| 测试（内存 SQLite） | 每个测试独立内存库 |
| 生产（PostgreSQL/MySQL） | 连接池大小 10-20，超时 30s |

## 执行流程

```python
# 1. 从 SQLBuilder 获取 SQL
sql = builder.build(dsl)

# 2. 安全扫描
scanner.scan(sql)  # 失败 → 拒绝

# 3. 沙箱预检
sandbox.check(sql)  # 有风险 → 人工审核

# 4. 执行
result = executor.execute(sql)
# 返回: [{"region": "华东", "sales_amount": 150000}, ...]

# 5. 后处理（如需）
if post_processor.should_post_process(dsl):
    result = post_processor.process(result, dsl)
```

## 错误处理

| 错误类型 | 处理方式 |
|---------|---------|
| 语法错误 | 返回 DSL 修正节点，LLM 重试 |
| 权限错误 | 返回 403，记录审计日志 |
| 超时 | 标记风险，建议简化查询 |
| 连接失败 | 重试 3 次，失败返回 503 |

## 未来增强

| 增强项 | 说明 | 优先级 |
|--------|------|--------|
| 异步执行 | 大查询改为后台执行，SSE 通知结果 | P2 |
| 结果流式返回 | 分页流式返回，减少内存占用 | P2 |
| 查询缓存 | 相同 SQL 命中缓存，直接返回 | P3 |
| 只读副本路由 | 读查询路由到只读副本 | P3 |
