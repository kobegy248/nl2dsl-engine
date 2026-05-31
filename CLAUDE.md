# NL2DSL - 自然语言到 DSL 智能问数系统

## 项目概述

NL2DSL 是一个企业级智能问数系统。核心思想：**AI 负责语义理解，系统负责执行治理**。

与传统 NL2SQL 不同，本系统采用分层架构：

```
自然语言 → Agent 编排层（意图识别 + 任务分解）
  → 简单查询 → LangGraph StateGraph（单查询 DSL→SQL→执行）
  → 复杂查询 → Dispatcher（多子查询并行/串行调度）
    → Aggregator（结果聚合）→ Explainer（自然语言解释）
```

这样做的好处：SQL 可校验、权限可控、查询可优化、多数据库方言可适配；复杂查询自动拆解，多子查询并行执行，结果智能聚合。

- **技术栈**: FastAPI + LangGraph + SQLAlchemy + sqlglot + Milvus Lite + BGE Embedder
- **部署形态**: 后端 FastAPI + 前端 React/Vite/AntD
- **LLM 接入**: 智谱 GLM-4.5-Air（默认）/ 通义千问 / Ollama 本地，所有 OpenAI 兼容接口
- **向量模型**: BGE-base-zh-v1.5（768 维，本地推理）
- **插件框架**: 组件可插拔（Registry）+ 节点可扩展（Pipeline 钩子）
- **多域支持**: 自动发现 `configs/` 下多个业务域，每个域独立 DB + Milvus + RAG

## 快速开始

```bash
# 安装依赖
pip install -e ".[dev]"
cd web && npm install

# 复制环境变量模板并编辑
cp .env.example .env

# 启动后端（首次自动初始化向量库）
uvicorn nl2dsl.api:app --reload --host 0.0.0.0 --port 8000

# 启动前端
cd web && npm run dev

# 运行测试
pytest                    # 全部测试
pytest tests/unit/        # 只跑单元测试
pytest --cov=nl2dsl --cov-report=html  # 带覆盖率
```

## 核心概念

### DSL（领域特定语言）

DSL 是 LLM 和系统之间的契约。LLM **只负责生成 DSL（JSON）**，不直接生成 SQL。

```json
{
  "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
  "dimensions": ["product_name", "brand"],
  "filters": {
    "op": "and",
    "children": [
      {"field": "region", "operator": "=", "value": "华东"},
      {"field": "order_date", "operator": "between", "value": ["2024-01-01", "2024-12-31"]}
    ]
  },
  "having": [{"field": "sales_amount", "operator": ">", "value": 10000}],
  "order_by": [{"field": "sales_amount", "direction": "desc"}],
  "limit": 10,
  "data_source": "orders",
  "time_field": "order_date",
  "time_range": ["2024-01-01", "2024-12-31"]
}
```

关键约束：
- `field` 必须是语义层已注册的维度名；`metric` 必须是语义层已注册的指标名
- `filters` 支持**条件树**（`and`/`or`/`not` 嵌套），同时兼容旧版 flat list
- 支持的操作符：`=`、`!=`、`>`、`<`、`>=`、`<=`、`between`、`in`、`like`、`is_null`
- 支持 `having`（对聚合结果过滤）、`time_field` + `time_range`（时间范围查询）
- 无 `limit` 时默认注入 `limit: 100`，最多 10000；禁止 SELECT *

### RAG 4 集合检索

| 集合 | 来源 YAML | 内容 | 检索策略 |
|------|---------|------|---------|
| `schema` | metrics.yaml | 维度 + 指标定义 | jieba 切词，向量近邻 |
| `metrics` | metrics.yaml | 指标计算式 | jieba 切词，向量近邻 |
| `terms` | terms.yaml | 业务术语 + 别名 | jieba 切词，向量近邻 |
| `history` | history.yaml | 问题→DSL 示例 | 整句语义检索 |

### 意图系统

`configs/intents.yaml` 定义了 7 种查询意图，新增意图无需改代码：

| 意图 | 关键词 | 分解策略 | 聚合策略 |
|------|--------|---------|---------|
| `compare` | 对比、比较、同比、环比 | 按对比对象拆分 | diff + growth_rate |
| `trend` | 趋势、走势、增长、下降 | 按时间维度分组 | trend_direction |
| `correlation` | 关联、影响、相关 | 按指标拆分 | pearson |
| `proportion` | 占比、构成、贡献度 | 总计 + 分组 | proportion |
| `sequential` | 先查、然后、再查 | 顺序执行 | sequential_filter |
| `ranking` | 排名、Top、第几 | 排序 + 取 Top | ranking |
| `single_query` | （默认兜底）| 透传 | 透传 |

### Agent 编排层

Agent 层负责复杂查询的宏观编排，Graph 层负责单查询的微观执行。

```
AgentOrchestrator.run()
  → _extract_entities()          提取指标、维度、时间范围
  → AgentController.route()      路由决策
      → SimpleExecutionPlan      单查询 → 直接走 LangGraph
      → ComplexExecutionPlan     多子查询 → Dispatcher → Aggregator → Explainer
      → ExplorationPlan          探索式（MVP 委托给 Simple）
  → _generate_explanation()      生成自然语言解释
```

**Dispatcher**：管理子查询依赖关系，独立子查询并行执行（最多 3 个并发），依赖子查询串行执行。每个子查询通过 `domain_context.graph.ainvoke()` 进入 LangGraph 流水线。

**Aggregator**：按意图类型聚合结果——`compare` 计算 diff 和 growth_rate，`trend` 检测方向，`correlation` 计算 Pearson 相关系数。

### 插件框架

Engine 提供**组件可插拔**和**节点可扩展**能力：

- **Registry** — 组件注册表（LLM、SQLBuilder、Validator 等）
- **Pipeline** — 节点链路 + 钩子映射（before/after/replace/add_node）
- **Plugin** — 扩展入口，通过 `register(engine)` 注册自定义逻辑

## 查询链路（双层架构）

### 完整流程

```
用户请求 → API 层
  → AgentOrchestrator
    → 实体提取（metrics / dimensions / time_range）
    → AgentController 路由
      ├── SimpleExecutionPlan ──→ 构建单查询 Plan
      │                           → domain_context.graph.ainvoke()
      │                           → LangGraph 单查询管道（见下）
      │                           → 返回 AgentResult
      │
      ├── ComplexExecutionPlan ─→ Planner 分解为多个 SubQuery
      │                           → Dispatcher 调度（并行/串行 + 依赖管理）
      │                           → 每个子查询走 LangGraph 单查询管道
      │                           → Aggregator 按意图聚合结果
      │                           → Explainer 生成自然语言解释
      │                           → 返回 AgentResult
      │
      └── ExplorationPlan ──────→ MVP：委托给 SimpleExecutionPlan
```

### LangGraph 单查询管道

```
START
  │
  ▼
clarification（歧义检测）──[需要澄清]──> END
  │[继续]
  ▼
plan（意图分类）──[非 single_query]──> 出图给 AgentOrchestrator
  │[single_query]
  ▼
decompose（复杂查询改写）
  │
  ▼
validation 子图（RAG → LLM 生成 DSL → 校验 → 失败自动修正）
  │
  ▼
permission_check 子图（行级权限 + 列级权限）
  │
  ▼
resolve_semantic（指标名 → SQL 表达式）
  │
  ▼
confidence（置信度评估）──[< 0.6]──> 路由到澄清
  │[≥ 0.6]
  ▼
build_sql（SQLAlchemy Core 构建）
  │
  ▼
scan_sql（安全扫描）
  │
  ▼
sandbox_check（沙箱预检）
  → 不通过 → human_review（人工确认）
  │[通过]
  ▼
execute_sql（数据库执行）
  → 失败 → simplify_dsl → 重试
  │
  ▼
verify_dsl（执行后自检）
  │
  ▼
explain（自然语言解释）
  │
  ▼
END
```

## 目录结构

```
nl2dsl/
├── api.py                  # FastAPI 应用入口
├── api_factory.py          # FastAPI App 工厂（含 Agent 层集成）
├── config.py               # 配置管理（Pydantic Settings）
├── domain_context.py       # 领域上下文（每个域的独立运行时）
├── engine.py               # 引擎入口：插件加载、StateGraph 编译、RAG 自检
├── plugin.py               # 插件框架：Registry + Pipeline + Plugin ABC
├── protocols.py            # 组件 Protocol 定义
├── exceptions.py           # 自定义异常体系
├── agent/                  # Agent 智能编排层
│   ├── orchestrator.py     # 顶层编排器：plan → dispatch → aggregate → explain
│   ├── controller.py       # 路由控制器：Simple / Complex / Exploration
│   ├── planner.py          # 意图识别 + 任务分解（LLM + 规则 fallback）
│   ├── dispatcher.py       # 子查询调度器：并行(max=3) / 串行 / 依赖管理
│   ├── aggregator.py       # 结果聚合器：compare / trend / correlation
│   ├── explainer.py        # 自然语言解释生成（LLM + 模板 fallback）
│   ├── confidence.py       # 三维度置信度评估（syntax / semantic / history）
│   ├── resolver.py         # 实体解析器：自然语言 → 标准标识符
│   ├── strategies.py       # 意图策略注册表（从 intents.yaml 加载）
│   ├── feedback_processor.py  # 用户反馈处理器
│   └── models.py           # Agent 数据模型（SubQuery / Plan / AgentResult 等）
├── dsl/                    # DSL Schema、校验器、构建工具
│   ├── models.py           # DSL / Filter / FilterTreeNode / Having 等模型
│   ├── validator.py        # DSL 校验器
│   ├── semantic_validator.py  # 语义验证器
│   ├── builder.py          # DSL 构建工具
│   └── generator.py        # DSL 生成辅助
├── graph/                  # LangGraph StateGraph 查询管道
│   ├── state.py            # QueryState TypedDict
│   ├── nodes.py            # 节点函数工厂
│   ├── edges.py            # 条件路由
│   ├── subgraphs.py        # 权限检查子图 + 验证子图
│   └── builder.py          # StateGraph 组装
├── llm/                    # Prompt 模板 + LLM 客户端
│   ├── client.py
│   └── prompts.py
├── rag/                    # 向量存储 + Embedder + 检索器 + 同步
│   ├── base.py
│   ├── embedder.py
│   ├── retriever.py
│   ├── reranker.py
│   ├── store.py
│   └── sync.py
├── permission/             # 行级权限 + 列级权限 + 脱敏
│   ├── row_level.py
│   ├── column_level.py
│   └── models.py
├── query/                  # 歧义检测 + 查询改写 + 沙箱 + 后处理
│   ├── clarification.py
│   ├── sandbox.py
│   └── post_processor.py
├── semantic/               # 语义层注册中心 + 解析器
│   ├── registry.py
│   └── resolver.py
├── sql_engine/             # SQLAlchemy 构建 + 扫描 + 执行 + 方言转换
│   ├── builder.py
│   ├── scanner.py
│   ├── executor.py
│   └── dialect.py
├── audit/                  # 审计日志
│   └── logger.py
├── feedback/               # 用户纠错反馈
│   └── collector.py
├── planner/                # 传统查询规划器（保留，部分逻辑迁移至 agent/planner.py）
│   ├── optimizer.py
│   └── router.py
└── utils/                  # 日志工具
    └── logger.py

configs/                    # YAML 配置
├── intents.yaml            # 意图配置（7 种意图，新增无需改代码）
├── metrics.yaml            # 指标 / 维度 / 数据源定义
├── terms.yaml              # 业务术语 + 别名映射
├── history.yaml            # 历史 few-shot 示例
├── permissions.yaml        # 权限策略
└── *_metrics.yaml          # 多域配置（自动发现）

web/                        # React + Vite 前端
scripts/                    # 工具脚本
tests/                      # 单元 / 集成 / E2E 测试
data/                       # SQLite 数据 + Milvus 向量库 + 测试结果
logs/                       # 日志文件
```

## 开发规范

- **格式化**: `ruff format .`
- **Lint**: `ruff check .`
- **类型检查**: `mypy --strict`
- **行长度**: 100
- LLM 调用在测试中**必须 Mock**（避免 API 费用）
- 数据库测试使用 SQLite 内存库
- RAG 测试使用 `MockEmbedder`

## 配置说明

环境变量前缀 `NL2DSL_`：

| 变量 | 必填 | 说明 |
|------|------|------|
| `NL2DSL_LLM_API_KEY` | 否 | LLM API 密钥，不配置时用 Mock |
| `NL2DSL_LLM_BASE_URL` | 否 | API 基础 URL |
| `NL2DSL_LLM_MODEL` | 否 | 模型名，默认 `glm-4.5-air` |
| `NL2DSL_MILVUS_URI` | 否 | Milvus Lite 路径 |
| `NL2DSL_DB_URL` | 否 | 数据库连接串 |
| `NL2DSL_MAX_LIMIT` | 否 | 单次最大返回行数，默认 10000 |
| `NL2DSL_QUERY_TIMEOUT` | 否 | 查询超时（秒），默认 30 |

## 常用开发任务

### 添加新指标

1. 编辑 `configs/metrics.yaml` 添加指标定义
2. 编辑 `configs/terms.yaml` 添加口语别名
3. 编辑 `configs/history.yaml` 添加示例问题
4. 重启后端（自动同步到向量库）

### 添加新意图

1. 编辑 `configs/intents.yaml`，新增意图节点：
   ```yaml
   my_intent:
     keywords: ["关键词1", "关键词2"]
     decomposition: split_by_objects    # 或 single_with_time_grouping / total_plus_groups 等
     aggregation: diff                  # 或 trend_direction / pearson / proportion 等
     description: "意图描述"
   ```
2. 如需新聚合策略，在 `nl2dsl/agent/aggregator.py` 中扩展 `Aggregate.run()`
3. 如需新分解策略，在 `nl2dsl/agent/planner.py` 中扩展 `Planner.plan()`
4. 添加单元测试 `tests/unit/test_agent_planner.py`

### 调试 DSL 生成问题

1. 调 `/api/v1/debug/rag?q=...` 看 RAG context
2. 检查日志：`grep "LLM raw output" logs/nl2dsl.log`
3. 检查 `_parse_llm_output` / `_post_process_dsl` / `_semantic_fix_dsl`

### 添加 StateGraph 节点

1. `nl2dsl/graph/nodes.py` 创建工厂函数（`@with_error_handler`）
2. `nl2dsl/graph/edges.py` 添加路由函数
3. `nl2dsl/graph/builder.py` 注册节点和边
4. 添加单元测试

### 调试 Agent 编排问题

1. 检查 `AgentOrchestrator.run()` 日志，确认实体提取和路由决策
2. 检查 `AgentController.route()` 返回的 ExecutionPlan 类型
3. 复杂查询检查 `Dispatcher` 日志，确认子查询分解和依赖关系
4. 调 `/api/v1/query/stream` 看 SSE 事件流

## 技术决策要点

1. **LLM 只生成 DSL 不生成 SQL**：DSL 可校验、可修正、可做权限控制
2. **RAG 分 4 集合不同策略**：短词用关键词检索，问句用语义检索
3. **启动自检同步**：改 YAML 重启即生效，增量同步避免重复加载模型
4. **SQLAlchemy Core 而非 ORM**：表达式树级别控制，适合动态 SQL 构建
5. **LangGraph StateGraph**：条件分支、可观测性、检查点恢复、流式输出
6. **SQLite 默认数据库**：零部署成本，生产环境可切换 MySQL/PostgreSQL
7. **LLM 输出三层兜底**：正则提取 JSON → 字段补全 → 硬约束修正
8. **双层架构（Agent + Graph）**：Agent 负责宏观编排（意图识别、多查询调度、结果聚合），Graph 负责微观执行（单查询 DSL→SQL→数据）。分层解耦，复杂查询和简单查询走不同路径
9. **配置驱动意图**：新增意图无需改代码，修改 `configs/intents.yaml` 即可
10. **置信度评估不阻断**：syntax + semantic + history 三维度评分，低于阈值路由到澄清而非静默执行低质量查询
