# 33. 测试策略

| 层级 | 测试内容 | 策略 |
|------|---------|------|
| 单元测试 | DSL 校验器、权限注入、SQL 构建 | pytest，LLM 调用必须 Mock |
| 集成测试 | LLM DSL 生成、数据库方言执行 | pytest + 测试数据库容器 |
| E2E 测试 | 完整链路、错误场景 | pytest + FastAPI TestClient |
