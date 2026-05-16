# 04. 部署与性能

## 4.1 部署方案

### 4.1.1 依赖服务

```yaml
# docker-compose.yml
# 当前配置：Milvus Lite（本地文件）+ SQLite（本地文件）
# 无需额外 Docker 服务，无需独立数据库
services: {}
```

### 4.1.2 环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `NL2DSL_LLM_API_KEY` | LLM API 密钥 | `sk-...` |
| `NL2DSL_LLM_BASE_URL` | LLM API 基础 URL | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `NL2DSL_LLM_MODEL` | 模型名称 | `qwen-plus` |
| `NL2DSL_VECTOR_STORE_TYPE` | 向量存储类型 | `milvus_lite`（默认） |
| `NL2DSL_MILVUS_URI` | Milvus Lite 本地文件路径 | `./milvus_lite.db` |
| `NL2DSL_DB_URL` | SQLite 数据库路径 | `sqlite:///./nl2dsl.db` |
| `NL2DSL_MAX_LIMIT` | 单次查询最大返回行数 | `10000` |

> **数据库说明：** 使用 SQLite 单文件存储，业务数据和审计/元数据表存于同一文件，通过表前缀区分（如 `nl2dsl_audit_log`、`nl2dsl_enum_mappings`）。零配置、零部署，适合单机/内网环境。

## 4.2 性能考虑

- LLM 调用使用异步 + 连接池
- SQL 执行使用 SQLAlchemy 连接池
- Milvus 向量检索本地缓存热点查询
- 大查询增加超时保护（30s）
