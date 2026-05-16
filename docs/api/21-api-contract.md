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
  "user_id": "u123",
  "tenant_id": "t001"
}
```

**Response 示例：**
```json
{
  "status": "success",
  "data": [{"product_name": "产品A", "sales_amount": 150000}],
  "dsl": {...},
  "sql": "SELECT ...",
  "execution_time_ms": 150,
  "rows_scanned": 10000
}
```

## 21.2 管理接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/schema` | GET | 获取所有表结构 |
| `/api/v1/metrics` | GET/POST | 指标查询/注册 |
| `/api/v1/feedback` | POST | 提交 DSL 纠错反馈 |

## 21.3 枚举管理接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/admin/enums` | GET | 查询所有枚举映射 |
| `/api/v1/admin/enums` | POST | 新增映射 |
| `/api/v1/admin/enums/{id}` | PUT | 修改映射 |
| `/api/v1/admin/enums/refresh` | POST | 热更新缓存 |
