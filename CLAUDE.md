# NL2DSL — 自然语言到 DSL 智能问数系统

## 项目概述

NL2DSL 是一个企业级智能问数系统。核心思想：**AI 负责语义理解，系统负责执行治理**。

与传统 NL2SQL（自然语言直接转 SQL）不同，本系统采用分层架构：

```
自然语言 → LLM → DSL → 校验 → 权限注入 → Query Planner → SQLAlchemy → 标准 SQL → sqlglot 方言转换 → 执行
```

这样做的好处：SQL 可校验、权限可控、查询可优化、多数据库方言可适配。

- **技术栈**: FastAPI + LangGraph + SQLAlchemy + sqlglot + Milvus Lite
- **部署形态**: 纯后端 API 服务（FastAPI）
- **LLM 接入**: OpenAI / Claude / 通义千问 API（可配置切换）

## 快速开始

### 环境要求

- Python 3.11+

### 安装依赖

```bash
pip install -e ".[dev]"
```

### 初始化向量库

```bash
python scripts/init_vector_store.py
```

### 启动应用

```bash
uvicorn nl2dsl.api:app --reload --host 0.0.0.0 --port 8000
```

### 运行测试

```bash
# 全部测试
pytest

# 只跑单元测试
pytest tests/unit/

# 带覆盖率
pytest --cov=nl2dsl --cov-report=html
```

### 验证服务

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "查询华东地区销售额最高的 10 个产品",
    "user_id": "u001",
    "tenant_id": "t001"
  }'
```

## 核心概念

### DSL（领域特定语言）

DSL 是 LLM 和系统之间的契约。LLM **只负责生成 DSL（JSON）**，不直接生成 SQL。

```json
{
  "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
  "dimensions": ["product_name"],
  "filters": [
    {"field": "region", "operator": "=", "value": "华东"}
  ],
  "order_by": [{"field": "sales_amount", "direction": "desc"}],
  "limit": 10,
  "data_source": "orders"
}
```

关键约束：
- `field` 必须是语义层已注册的维度名（不是数据库原始列名）
- `metric` 必须是语义层已注册的指标名
- 无 `limit` 时系统自动注入默认 `limit: 100`
- 禁止 SELECT *

### 语义层

语义层通过 YAML 配置文件统一管理业务指标和数据模型：

```yaml
# configs/metrics.yaml
metrics:
  sales_amount:
    expr: SUM(order_amount)
    description: "销售额"

dimensions:
  product_name:
    column: product_name
    description: "产品名称"

data_sources:
  orders:
    table: order_fact
    metrics: [sales_amount]
    dimensions: [product_name, region]
```

**规则**：所有业务查询必须通过语义层，禁止直接引用数据库原始字段。

### 查询链路

```
用户请求
  → API 层接收（提取 user_id / tenant_id）
  → RAG 检索（召回相关表结构、指标定义、历史查询示例）
  → LLM 生成 DSL（基于检索到的上下文）
  → DSL 自检（LLM 检查字段/指标是否存在、逻辑是否合理）
  → Pydantic 校验（Schema / 类型 / 约束检查）
  → 权限注入（行级过滤 + 列级黑名单）
  → 语义展开（指标名 → SQL 表达式）
  → Query Planner（Join 推导、优化路由）
  → SQLAlchemy 构建标准 SQL
  → sqlglot 方言转换（MySQL / PostgreSQL / ClickHouse / Doris）
  → 数据库执行
  → 结果脱敏
  → 审计日志记录
  → 返回响应
```

## 目录结构

```
nl2dsl/
├── api.py              # FastAPI 应用入口，路由注册
├── config.py           # 配置管理（Pydantic Settings）
├── dsl/
│   ├── models.py       # Pydantic DSL Schema 定义
│   ├── validator.py    # DSL 校验器（字段存在性、操作符合法性、风险控制）
│   └── builder.py      # DSL 构建辅助工具
├── llm/
│   ├── agent.py        # LangGraph 工作流定义（RAG → 生成 → 自检 → 修正）
│   ├── prompts.py      # System Prompt / User Prompt 模板
│   └── client.py       # LLM API 客户端封装（OpenAI / Claude / 通义千问）
├── rag/
│   ├── store.py        # 向量存储抽象层（Milvus Lite / Milvus Server）
│   ├── embedder.py     # 文本嵌入（sentence-transformers）
│   └── retriever.py    # 检索逻辑（召回 → 重排序 → 组装上下文）
├── permission/
│   ├── models.py       # 权限模型定义
│   ├── row_level.py    # 行级权限注入（自动添加用户可见范围过滤）
│   └── column_level.py # 列级权限控制（敏感字段黑名单 + 脱敏规则）
├── planner/
│   ├── optimizer.py    # 查询优化规则（谓词下推、投影下推、聚合重写）
│   └── router.py       # 路由决策（预聚合表命中、Cache 命中）
├── semantic/
│   ├── registry.py     # 指标 / 维度 / 数据源注册中心（YAML 加载 + 内存缓存）
│   └── resolver.py     # 指标展开、Join 条件推导
├── sql_engine/
│   ├── builder.py      # SQLAlchemy Core 表达式构建
│   ├── dialect.py      # sqlglot 方言转换
│   └── executor.py     # 数据库连接池管理 + SQL 执行
├── audit/
│   └── logger.py       # 审计日志记录（查询全过程持久化）
└── feedback/
    └── collector.py    # 用户纠错反馈收集 + 自动学习闭环

tests/
├── unit/               # 单元测试（DSL 校验、权限注入、SQL 构建）
├── integration/        # 集成测试（LLM Mock、数据库方言执行）
└── e2e/                # 端到端测试（完整链路）

configs/
├── metrics.yaml        # 指标定义
├── schema.yaml         # 表结构定义
└── permissions.yaml    # 权限配置模板
```

## 开发规范

### 代码风格

- **格式化**: `ruff`（`ruff format .`）
- **Lint**: `ruff check .`（替代 flake8 + isort + pycodestyle）
- **类型检查**: `mypy --strict`
- **行长度**: 100

### 导入规范

- 使用**绝对导入**（`from nl2dsl.dsl.models import DSL`，不是 `from .models import DSL`）
- 第三方库 → 标准库 → 本地模块，按字母排序

### 命名规范

- 模块/包: `snake_case`
- 类: `PascalCase`
- 函数/变量: `snake_case`
- 常量: `UPPER_SNAKE_CASE`

### 测试规范

- LLM 调用在测试中**必须 Mock**（避免产生 API 费用）
- 数据库测试使用 SQLite 内存库或 Docker 测试容器
- RAG 测试使用内存向量存储（`MilvusClient(":memory:")`）
- 测试函数命名：`test_功能_场景_预期结果`

### 错误处理

- 自定义异常继承自 `NL2DSLException`
- 异常必须包含 `error_code`（供前端/调用方识别）
- API 层统一捕获并转换为标准错误响应格式

```python
# nl2dsl/exceptions.py
class NL2DSLException(Exception):
    error_code: str
    status_code: int = 500

class ValidationError(NL2DSLException):
    error_code = "VALIDATION_ERROR"
    status_code = 400

class PermissionError(NL2DSLException):
    error_code = "PERMISSION_DENIED"
    status_code = 403
```

## 配置说明

所有配置通过环境变量 + `.env` 文件管理，前缀 `NL2DSL_`。

| 变量 | 必填 | 说明 |
|------|------|------|
| `NL2DSL_LLM_API_KEY` | 是 | LLM API 密钥 |
| `NL2DSL_LLM_BASE_URL` | 否 | 自定义 API 基础 URL |
| `NL2DSL_LLM_MODEL` | 是 | 模型名称，如 `gpt-4`、`claude-3-sonnet` |
| `NL2DSL_VECTOR_STORE_TYPE` | 否 | 向量存储类型：`milvus_lite`（默认）或 `milvus_server` |
| `NL2DSL_MILVUS_URI` | 否 | Milvus Lite 本地文件路径，默认 `./milvus_lite.db` |
| `NL2DSL_MILVUS_HOST` | 否 | Milvus Server 地址，默认 `localhost` |
| `NL2DSL_MILVUS_PORT` | 否 | Milvus Server 端口，默认 `19530` |
| `NL2DSL_DB_URL` | 是 | 数据库连接串 |
| `NL2DSL_MAX_LIMIT` | 否 | 单次查询最大返回行数，默认 `10000` |
| `NL2DSL_QUERY_TIMEOUT` | 否 | 查询超时（秒），默认 `30` |

```python
# config.py 使用方式
from nl2dsl.config import settings

api_key = settings.llm_api_key
```

## 调试指南

### 查看 LLM 生成的 DSL（不执行）

```bash
curl -X POST http://localhost:8000/api/v1/query/dsl \
  -H "Content-Type: application/json" \
  -d '{"question": "...", "user_id": "u001"}'
```

### 查看 SQL 生成过程

在 `nl2dsl/sql_engine/builder.py` 和 `dialect.py` 中添加日志：

```python
import logging
logger = logging.getLogger(__name__)

# 在 build() 和 transpile() 中
logger.debug("Standard SQL: %s", standard_sql)
logger.debug("Dialect SQL: %s", dialect_sql)
```

### 查看 LangGraph 工作流执行状态

LangGraph 工作流节点会输出 `node` 级别的日志，通过日志中的 `langgraph:node` 标记追踪：

```
DEBUG:nl2dsl.llm.agent:Entering node: rag_retrieve
DEBUG:nl2dsl.llm.agent:Entering node: llm_generate
DEBUG:nl2dsl.llm.agent:Entering node: self_check
```

### 查看审计日志

审计日志写入配置的审计数据库表（或本地 SQLite）：

```sql
SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 10;
```

### 查看向量库内容（调试向量检索）

Milvus Lite 是本地文件存储，无需 Docker。数据文件默认在 `./milvus_lite.db`。

如需切换到 Milvus Server：

```bash
# docker-compose.yml 中取消 milvus 服务注释
docker-compose up -d milvus
```

然后修改环境变量 `NL2DSL_VECTOR_STORE_TYPE=milvus_server`。

## 常见开发任务

### 添加新指标

1. 编辑 `configs/metrics.yaml`
2. 添加指标定义（expr、description、unit）
3. 重启服务（或调用热重载接口）
4. 在 `tests/unit/semantic/test_registry.py` 添加测试

### 添加新数据库方言支持

1. 确认 `sqlglot` 支持该方言（`sqlglot.Dialect.get_or_raise("dialect_name")`）
2. 在 `nl2dsl/sql_engine/dialect.py` 的 `SUPPORTED_DIALECTS` 中添加
3. 在 `tests/integration/test_dialect.py` 中添加该方言的转换测试

### 调试 DSL 生成失败

1. 先调用 `/api/v1/query/dsl` 获取生成的原始 DSL
2. 检查 DSL 中的 `field` 是否在语义层注册
3. 检查 `operator` 是否在允许列表中
4. 查看 LLM 的原始输出（开启 DEBUG 日志）

### 添加权限规则

1. 行级权限：编辑 `configs/permissions.yaml`，添加 `row_filters`
2. 列级权限：编辑敏感字段列表（`nl2dsl/permission/column_level.py` 中的 `SENSITIVE_COLUMNS`）
3. 脱敏规则：在 `nl2dsl/permission/column_level.py` 的 `MASKING_RULES` 中添加

## 技术决策记录

### 为什么不用 Calcite（原方案）？

原参考方案使用 Java Apache Calcite 做查询编译。本方案改用全 Python 栈：

- **SQLAlchemy Core**: 负责表达式树构建
- **sqlglot**: 负责 SQL 解析和多方言转换

原因：统一技术栈，降低部署复杂度，sqlglot 支持 20+ 方言且纯 Python。

### 为什么 LLM 只生成 DSL 不生成 SQL？

- DSL 是结构化 JSON，可校验、可修正
- SQL 是自由文本，出错后难以定位和修复
- DSL 层级可做权限控制（在编译为 SQL 前注入过滤条件）
- DSL 可做查询优化（在编译前做重写）

### 为什么用 LangGraph 而不是直接调用 LLM？

LangGraph 提供：
- 多步骤工作流可视化
- 节点级重试和错误恢复
- 状态管理（RAG 上下文在节点间传递）
- 条件分支（自检失败 → 修正 → 重试）
