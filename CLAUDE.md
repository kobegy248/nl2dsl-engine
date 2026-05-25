# NL2DSL - 自然语言到 DSL 智能问数系统

## 项目概述

NL2DSL 是一个企业级智能问数系统。核心思想：**AI 负责语义理解，系统负责执行治理**。

与传统 NL2SQL（自然语言直接转 SQL）不同，本系统采用分层架构：

```
自然语言 → RAG 检索 → LLM → DSL → 校验 → 权限注入 → 语义解析 → SQLAlchemy → 标准 SQL → 执行
```

这样做的好处：SQL 可校验、权限可控、查询可优化、多数据库方言可适配。

**插件框架**：在 LangGraph 之上包一层 Engine，通过 Registry（组件注册表）+ Pipeline（节点钩子）+ Plugin（扩展入口）实现可插拔和可扩展。

**RAG 配置驱动**：业务术语 / 历史示例通过 YAML 维护，后端启动自动同步到向量库。

- **技术栈**: FastAPI + LangGraph + LangChain + SQLAlchemy + sqlglot + Milvus Lite + BGE Embedder
- **部署形态**: 后端 FastAPI + 前端 React/Vite/AntD
- **LLM 接入**: 智谱 GLM-4.5-Air（默认）/ 通义千问 / Ollama 本地，所有 OpenAI 兼容接口
- **向量模型**: BGE-base-zh-v1.5（768 维，本地推理）
- **插件框架**: 组件可插拔（Registry）+ 节点可扩展（Pipeline 钩子）

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+（前端）
- torch >= 2.6（sentence-transformers 强制要求，CVE-2025-32434）

### 安装依赖

```bash
# 后端
pip install -e ".[dev]"

# 前端
cd web && npm install
```

### 配置环境变量

```bash
# 复制模板
cp .env.example .env

# 编辑 .env 文件，三种 LLM 接入方式：

# 1) 智谱 AI（默认，glm-4.5-air）
NL2DSL_LLM_API_KEY=your-zhipu-api-key
NL2DSL_LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
NL2DSL_LLM_MODEL=glm-4.5-air

# 2) Ollama 本地
NL2DSL_LLM_API_KEY=ollama
NL2DSL_LLM_BASE_URL=http://localhost:11434/v1
NL2DSL_LLM_MODEL=qwen3:8b

# 3) 通义千问（DashScope）
NL2DSL_LLM_API_KEY=your-dashscope-api-key
NL2DSL_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
NL2DSL_LLM_MODEL=qwen-plus
```

### 启动应用

```bash
# 后端（首次启动自动初始化向量库）
uvicorn nl2dsl.api:app --reload --host 0.0.0.0 --port 8000

# 前端
cd web && npm run dev
```

### 运行测试

```bash
# 后端：全部测试
pytest

# 只跑单元测试
pytest tests/unit/

# 带覆盖率
pytest --cov=nl2dsl --cov-report=html

# 前端 E2E（Playwright）
cd web && npx playwright test

# RAG 4 集合覆盖度测试（需后端运行）
python scripts/test_rag_coverage.py
```

### 验证服务

```bash
# Health 检查
curl http://localhost:8000/health

# 自然语言查询
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "查询华东地区销售额最高的 10 个产品",
    "user_id": "u001",
    "tenant_id": "t001"
  }'

# 调试 RAG 检索（看 LLM 实际拿到了什么 context）
curl "http://localhost:8000/api/v1/debug/rag?q=各品牌的流水"
```

## 核心概念

### DSL（领域特定语言）

DSL 是 LLM 和系统之间的契约。LLM **只负责生成 DSL（JSON）**，不直接生成 SQL。

```json
{
  "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
  "dimensions": ["product_name", "brand"],
  "filters": [
    {"field": "region", "operator": "=", "value": "华东"}
  ],
  "order_by": [{"field": "sales_amount", "direction": "desc"}],
  "limit": 10,
  "data_source": "orders",
  "joins": [
    {"table": "customer_dim", "on_field": "customer_id", "join_type": "left", "alias": "c"},
    {"table": "product_dim", "on_field": "product_id", "join_type": "inner", "alias": "p"}
  ]
}
```

关键约束：
- `field` 必须是语义层已注册的维度名（不是数据库原始列名）
- `metric` 必须是语义层已注册的指标名
- 无 `limit` 时系统自动注入默认 `limit: 10`，最多 100
- `joins` 可选，支持 `inner`/`left`/`right` 三种 join 类型
- 禁止 SELECT *

### RAG 4 集合检索

向量库分 4 个集合，按用途采用不同检索策略：

| 集合 | 来源 YAML | 内容 | 检索策略 |
|------|---------|------|---------|
| `schema` | metrics.yaml | 维度 + 指标定义 | jieba 切词，向量近邻 |
| `metrics` | metrics.yaml | 指标计算式 | jieba 切词，向量近邻 |
| `terms` | terms.yaml | 业务术语 + 别名（"流水→gmv"）| jieba 切词，向量近邻 |
| `history` | history.yaml | "问题→DSL"示例 | **整句语义检索** |

设计逻辑：
- 短命名实体（指标、维度、术语别名）适合关键词级别检索
- 完整问句适合整句语义相似度（找表达不同但意图相同的示例）

### 启动自检同步

`nl2dsl/rag/sync.py` 实现增量同步：

1. 启动时读 `.rag_sync_state.json`，比较各 YAML 的 mtime
2. mtime 新于上次同步时间 → 增量重灌该集合
3. 集合不存在 → 创建并全量灌
4. 都最新 → 跳过 BGE 模型加载（启动快）

YAML 改完不需要手动跑脚本，重启后端即可。

### 插件框架

Engine 是 LangGraph 之上的框架层，提供**组件可插拔**和**节点可扩展**能力：

```python
from nl2dsl import Engine, Plugin

# 方式1：零配置开箱即用
engine = Engine()
app = engine.build_fastapi_app()

# 方式2：用插件扩展
engine = Engine()
engine.use(OllamaPlugin())  # 替换 LLM 后端
app = engine.build_fastapi_app()
```

**三个核心对象**：

1. **`Registry`** — 组件注册表（key-value）。存储 LLM、SQLBuilder、Validator 等组件，支持按名称查找和覆盖。
2. **`Pipeline`** — 节点链路 + 钩子映射。支持 `before`/`after`/`replace`/`add_node` 操作。
3. **`Plugin`** — 扩展入口。通过 `register(engine)` 向 Registry 和 Pipeline 注册自定义逻辑。

**Protocol 定义**：`nl2dsl/protocols.py` 定义了 `LLMBackend`、`SQLBuilder`、`Validator` 等接口，现有类已自然适配。

### 语义层

语义层通过 YAML 配置文件统一管理业务指标和数据模型：

```yaml
# configs/metrics.yaml
metrics:
  sales_amount:
    expr: SUM(order_amount)
    description: "销售额"
  gmv:
    expr: SUM(order_amount)
    description: "成交总额"

dimensions:
  product_name:
    column: product_name
    description: "产品名称"

data_sources:
  orders:
    table: order_fact
    metrics: [sales_amount, gmv, order_count, avg_order_value, total_discount]
    dimensions: [product_name, brand, category, region, channel, customer_type]
    joins:
      product_dim:
        on: product_id
        type: inner
        alias: p
      customer_dim:
        on: customer_id
        type: left
        alias: c
```

```yaml
# configs/terms.yaml — 业务术语 + 别名（RAG 强匹配关键）
terms:
  gmv:
    aliases: [GMV, 成交总额, 交易额, 流水, ...]
    metric: gmv
    description: "成交总额 SUM(order_amount)"
  ...
```

```yaml
# configs/history.yaml — 问题 → DSL 示例（RAG few-shot 素材）
examples:
  - question: "查询华东地区销售额"
    dsl: {metrics: [...], dimensions: [region], filters: [...], ...}
  ...
```

**规则**：所有业务查询必须通过语义层，禁止直接引用数据库原始字段。

### 查询链路（LangGraph StateGraph）

```
用户请求
  → API 层接收（提取 user_id / tenant_id，构建 QueryState）
  → LangGraph StateGraph 执行:
    → clarification（歧义检测，有歧义直接返回）
    → validation 子图（RAG → LLM 生成 DSL → 校验 → 失败自动修正循环）
    → permission_check 子图（行级权限注入 → 列级权限检查）
    → resolve_semantic（指标名 → SQL 表达式）
    → build_sql（SQLAlchemy Core 构建）
    → scan_sql（安全扫描，简单/复杂查询不同策略）
    → sandbox_check（沙箱预检）
      → 不通过 → human_review（中断等待人工确认）
    → execute_sql（数据库执行）
      → 失败 → simplify_dsl → 重试
  → 审计日志记录（含完整 trace 链路）
  → 返回响应
```

**LangGraph 带来的能力：**
- **条件分支**: 校验失败自动修正、沙箱不通过人工审核、查询复杂度路由
- **检查点**: 流程可中断、可恢复（`InMemorySaver`）
- **流式输出**: `astream` 实时推送每个节点结果
- **子图封装**: 权限检查和验证逻辑独立封装为子图
- **统一错误处理**: `@with_error_handler` 装饰器捕获所有节点异常

## 目录结构

```
nl2dsl/
├── __init__.py             # 包导出：Engine, Plugin
├── api.py                  # FastAPI 应用入口，路由注册（主入口）
├── api_factory.py          # FastAPI App 工厂（用于 E2E 测试注入 mock 数据）
├── config.py               # 配置管理（Pydantic Settings，支持 .env 文件）
├── engine.py               # 引擎入口：插件加载、默认组件注册、StateGraph 编译、RAG 启动自检
├── plugin.py               # 插件框架：Registry + Pipeline + Plugin ABC
├── protocols.py            # 组件 Protocol 定义（LLMBackend、SQLBuilder 等）
├── exceptions.py           # 自定义异常体系
├── dsl/
│   ├── models.py           # Pydantic DSL Schema 定义（含 Join 模型）
│   ├── validator.py        # DSL 校验器（字段存在性、操作符合法性）
│   └── builder.py          # DSL 构建辅助工具
├── graph/                  # LangGraph StateGraph 查询管道（核心链路）
│   ├── __init__.py
│   ├── state.py            # QueryState TypedDict（含 Annotated reducer）
│   ├── nodes.py            # 所有节点函数 + @with_error_handler 装饰器
│   ├── edges.py            # 条件路由函数
│   ├── subgraphs.py        # 权限检查子图 + 验证子图
│   └── builder.py          # StateGraph 组装 + 编译
├── llm/
│   ├── prompts.py          # System Prompt / User Prompt 模板（含术语映射 + few-shot）
│   └── client.py           # LLM API 客户端封装（OpenAI SDK）
├── rag/
│   ├── store.py            # 向量存储抽象层（Milvus Lite）
│   ├── embedder.py         # BGE 中文向量模型 + MockEmbedder（测试用）
│   ├── retriever.py        # 混合检索：keyword（schema/metrics/terms）+ semantic（history）
│   └── sync.py             # 配置驱动的启动自检同步
├── permission/
│   ├── models.py
│   ├── row_level.py        # 行级权限注入（自动添加用户可见范围过滤）
│   └── column_level.py     # 列级权限控制（敏感字段黑名单 + 脱敏规则）
├── query/
│   ├── clarification.py    # 歧义检测器
│   └── sandbox.py          # 查询沙箱（EXPLAIN + LIMIT 预览）
├── semantic/
│   ├── registry.py         # 指标 / 维度 / 数据源注册中心（YAML 加载）
│   └── resolver.py         # 指标展开、value_map 转换
├── sql_engine/
│   ├── builder.py          # SQLAlchemy Core 表达式构建（支持多表 JOIN）
│   ├── scanner.py          # SQL 安全扫描
│   ├── executor.py         # SQL 执行器
│   └── dialect.py          # sqlglot 方言转换
├── audit/
│   └── logger.py           # 审计日志（INSERT OR REPLACE 防重复）
├── feedback/
│   └── collector.py        # 用户纠错反馈收集
└── utils/
    └── logger.py           # 统一日志（控制台 + 文件 + 按天轮转）

configs/
├── metrics.yaml            # 指标 + 维度 + 数据源 → schema/metrics 集合
├── terms.yaml              # 业务术语 + 别名 → terms 集合
├── history.yaml            # 问题→DSL 示例 → history 集合
└── permissions.yaml        # 行级/列级/脱敏权限配置

web/                        # React + Vite 前端
├── src/
│   ├── pages/
│   │   ├── QueryPage.tsx   # 自然语言查询工作台
│   │   └── AdminPage.tsx   # 管理后台（指标管理 / 审计日志 / 权限配置）
│   ├── components/
│   │   ├── query/          # QueryInput / ResultTable / ResultChart / ResultTabs / QueryProgress
│   │   ├── admin/          # AuditLogTable / AuditTraceDetail / MetricList / ...
│   │   └── common/         # Loading / ErrorAlert / JsonViewer
│   ├── api/
│   │   ├── client.ts       # axios 客户端（timeout=120s 兼容慢 LLM）
│   │   ├── query.ts
│   │   └── audit.ts
│   ├── hooks/              # useQuery / useAudit 等 React Query hooks
│   └── types/api.ts        # 与后端契约对齐的 TypeScript 类型
├── tests/e2e/              # Playwright 端到端测试
│   ├── query.spec.ts
│   └── admin.spec.ts
├── playwright.config.ts    # timeout=60s, workers=1, screenshot='on'
└── test-screenshots/       # 自动截图归档

scripts/
├── init_vector_store.py    # 手动同步入口（启动自检通常已覆盖）
└── test_rag_coverage.py    # RAG 4 集合覆盖度测试（含 8 个 case）

tests/
├── unit/                   # 单元测试
├── integration/            # 集成测试
└── e2e/                    # 端到端测试

logs/
├── nl2dsl.log              # 全量日志（utf-8 编码）
└── nl2dsl.error.log        # 错误日志

.rag_sync_state.json        # YAML 同步状态（mtime 记录）
milvus_lite.db/             # 向量库数据目录
nl2dsl.db                   # SQLite 业务数据 + 审计日志
```

## 开发规范

### 代码风格

- **格式化**: `ruff`（`ruff format .`）
- **Lint**: `ruff check .`
- **类型检查**: `mypy --strict`
- **行长度**: 100

### 测试规范

- LLM 调用在测试中**必须 Mock**（避免产生 API 费用）
- 数据库测试使用 SQLite 内存库
- RAG 测试使用 `MockEmbedder`
- 前端 E2E 使用 Playwright，结果截图归档在 `web/test-screenshots/`

### 错误处理

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
| `NL2DSL_LLM_API_KEY` | 否 | LLM API 密钥。不配置时使用 Mock |
| `NL2DSL_LLM_BASE_URL` | 否 | API 基础 URL，默认 DashScope 兼容地址 |
| `NL2DSL_LLM_MODEL` | 否 | 模型名，默认 `qwen-plus`，已切到 `glm-4.5-air` |
| `NL2DSL_MILVUS_URI` | 否 | Milvus Lite 本地文件路径，默认 `./milvus_lite.db` |
| `NL2DSL_DB_URL` | 否 | 数据库连接串，默认 `sqlite:///./nl2dsl.db` |
| `NL2DSL_MAX_LIMIT` | 否 | 单次查询最大返回行数，默认 `10000` |
| `NL2DSL_QUERY_TIMEOUT` | 否 | 查询超时（秒），默认 `30` |

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/api/v1/query` | 自然语言查询 |
| POST | `/api/v1/query/dsl` | 仅生成 DSL |
| POST | `/api/v1/query/execute` | 直接执行 DSL |
| POST | `/api/v1/query/stream` | 流式查询（SSE） |
| POST | `/api/v1/query/resume` | 恢复中断流程 |
| GET | `/api/v1/schema` | 获取语义层 Schema |
| GET | `/api/v1/metrics` | 获取指标列表 |
| POST | `/api/v1/feedback` | 提交纠错反馈 |
| GET | `/api/v1/admin/audit/queries` | 审计日志列表 |
| GET | `/api/v1/admin/audit/queries/{id}` | 审计日志详情 |
| GET | `/api/v1/debug/rag?q=...` | **调试**：查看 RAG 检索结果与拼成的 context |

## 调试指南

### 查看 RAG 检索内容（最实用）

```bash
curl "http://localhost:8000/api/v1/debug/rag?q=各品牌的流水"
```

返回每个集合的命中项 + 完整 prompt context。**LLM 没按预期生成 DSL 时首先查这个**，确认 RAG 给了 LLM 足够信息。

### 查看 LLM 原始输出

后端日志会打出每次 LLM 的完整返回（含 markdown 和解释文字）：

```bash
# Windows
type logs\nl2dsl.log | findstr "LLM raw output"

# Linux/macOS
grep "LLM raw output" logs/nl2dsl.log
```

`_parse_llm_output` 用正则从中提取 JSON 代码块，所以 LLM 即使返回大段解释也能正确解析。

### 查看审计日志

```bash
# 列表
curl "http://localhost:8000/api/v1/admin/audit/queries?limit=5"

# 详情（含 trace 链路）
curl "http://localhost:8000/api/v1/admin/audit/queries/{query_id}"
```

或直接打开前端 http://localhost:5173/admin → 审计日志页。

### 切换 LLM / Mock 模式

- **启用 LLM**: 在 `.env` 中配置 `NL2DSL_LLM_API_KEY`
- **纯 Mock 模式**: 删除或不配置 `NL2DSL_LLM_API_KEY`，系统使用关键词匹配生成 DSL

### 流式查询调试

```bash
curl -N -X POST http://localhost:8000/api/v1/query/stream \
  -H "Content-Type: application/json" \
  -d '{"question": "查询销售额", "user_id": "u001", "tenant_id": "t001"}'
```

### 强制重灌向量库

正常情况启动自检会同步。强制重建（如换向量模型时）：

```bash
# 关闭后端释放 Milvus 锁
# 删除整个数据目录
rm -rf milvus_lite.db .rag_sync_state.json
# 重启后端
uvicorn nl2dsl.api:app --host 0.0.0.0 --port 8000
```

或用脚本：

```bash
python scripts/init_vector_store.py --force
```

## 常见开发任务

### 添加新指标

1. 编辑 `configs/metrics.yaml`，添加 `expr` 和 `description`
2. **同时**编辑 `configs/terms.yaml`，给指标加几个口语别名
3. **同时**编辑 `configs/history.yaml`，加 2-3 个使用该指标的示例问题
4. 重启后端（启动自检自动同步到向量库）

### 调试 DSL 生成失败

1. 调 `/api/v1/debug/rag?q=...` 看 RAG 给了什么 context
2. 检查 LLM 日志：`grep "LLM raw output" logs/nl2dsl.log`
3. 如果 LLM 输出正确但最终 DSL 错 → 看 `_post_process_dsl` / `_semantic_fix_dsl` 是否覆盖
4. 如果 LLM 输出包含 markdown 但被回退到 mock → 检查 `_parse_llm_output` 是否正常解析

### 添加新的 StateGraph 节点

1. 在 `nl2dsl/graph/nodes.py` 中创建 `_make_*_node` 工厂函数（用 `@with_error_handler` 装饰）
2. 在 `nl2dsl/graph/edges.py` 中添加路由函数（如需条件分支）
3. 在 `nl2dsl/graph/builder.py` 中注册节点和边
4. 在 `tests/unit/test_graph_nodes.py` 中加单元测试

### 开发自定义插件

```python
from nl2dsl import Engine, Plugin

class OllamaPlugin(Plugin):
    def register(self, engine):
        engine.register("llm", OllamaLLM(model="qwen3:8b"))

engine = Engine()
engine.use(OllamaPlugin())
app = engine.build_fastapi_app()
```

### 前端开发

```bash
cd web
npm run dev       # 启动 dev server（默认 :5173）
npx playwright test  # 运行 E2E（前端工作台 + 管理后台共 12 个用例）
```

注意事项：
- axios 客户端 timeout=120s（兼容慢 LLM）
- 后端审计 API 返回字段：`query_id`（不是 id）、`created_at`（不是 timestamp）
- 详情接口返回 `{status, item: {...}}`，前端 hook 已自动解包

## 技术决策记录

### 为什么 LLM 只生成 DSL 不生成 SQL？

- DSL 是结构化 JSON，可校验、可修正
- SQL 是自由文本，出错后难以定位和修复
- DSL 层级可做权限控制（在编译为 SQL 前注入过滤条件）
- DSL 可做查询优化（在编译前做重写）

### 为什么 RAG 分 4 个集合且检索策略不同？

- 短命名实体（指标/维度/术语别名）：**jieba 切词关键词检索**，更准确
- 历史问句：**整句语义检索**，能找到表达不同但意图相同的示例
- 一刀切的整句检索对短词召回差，反过来一刀切的关键词检索对完整问句召回差

### 为什么需要启动自检同步？

- 业务人员只懂 YAML，不会跑脚本
- 改完 YAML 重启即生效，闭环不断
- 增量同步避免每次重启都加载 BGE 模型
- 版本化的状态文件让 Docker 部署更可靠

### 为什么用 SQLAlchemy Core 而不是 ORM？

- Core 提供表达式树级别的控制，适合动态 SQL 构建
- ORM 的隐式行为（延迟加载、关系导航）不适合查询编译场景
- Core 与 sqlglot 配合更自然（表达式树 → SQL 字符串 → 方言转换）

### 为什么使用 LangGraph StateGraph？

- **条件分支**: 原生支持校验失败自动修正、沙箱不通过人工审核
- **可观测性**: LangSmith 自动追踪每个节点的输入输出和耗时
- **检查点/中断恢复**: `InMemorySaver` 支持 human-in-the-loop
- **流式输出**: `astream` 实时推送每个阶段中间结果
- **子图封装**: 权限检查、验证循环等复杂逻辑可独立封装
- **统一错误处理**: `@with_error_handler` 装饰器标准化异常捕获

### 为什么用 SQLite 作为默认数据库？

- 零部署成本，适合开发和演示
- 文件级存储（`nl2dsl.db`），数据持久化
- 生产环境可通过 `NL2DSL_DB_URL` 切换为 MySQL/PostgreSQL 等

### LLM 输出后处理三层兜底

LLM 不稳定是常态，系统做了 3 层处理保证可用：

1. **`_parse_llm_output`** — 正则从 markdown 代码块中提取 JSON，兼容大段解释文字
2. **`_post_process_dsl`** — 字段补全（metrics 缺 func/field 时根据 alias 反查）
3. **`_semantic_fix_dsl`** — 硬约束兜底（filter 中地区/渠道/客户类型、limit 中的 top-N 数字）

metrics/dimensions 的语义识别完全交给 LLM + RAG（terms 集合提供别名映射），不在代码里写关键词列表。
