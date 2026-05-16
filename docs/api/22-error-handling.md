# 22. 错误处理

## 22.1 错误分类

| 错误类型 | HTTP 状态码 | 说明 |
|---------|------------|------|
| ValidationError | 400 | DSL 校验失败 |
| PermissionError | 403 | 权限不足 |
| SemanticError | 400 | 语义层解析失败（指标不存在等） |
| QueryError | 400 | 查询执行失败（SQL 错误） |
| LLMError | 502 | LLM 服务异常 |
| RateLimitError | 429 | 请求频率超限 |

## 22.2 错误响应格式

```json
{
  "status": "error",
  "error_code": "VALIDATION_ERROR",
  "message": "字段 'sale_amount' 不存在，是否指 'sales_amount'?",
  "suggestion": "请使用已注册的指标名"
}
```

## 22.3 歧义响应格式

```json
{
  "status": "ambiguous",
  "options": [
    {"term": "sales_amount", "description": "含税销售额"},
    {"term": "net_revenue", "description": "税后净营收"}
  ]
}
```
