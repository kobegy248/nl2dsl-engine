# 02. 系统架构

## 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                          API Layer (FastAPI)                     │
│  POST /api/v1/query  │  POST /api/v1/query/dsl  │  ...         │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                      LangGraph Workflow                          │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐           │
│  │RAG检索  │→ │LLM生成  │→ │DSL自检  │→ │权限注入 │           │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘           │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                      Core Engine                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │Semantic  │  │Query     │  │SQLBuilder│  │Dialect   │        │
│  │Layer     │  │Planner   │  │          │  │Converter │        │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                    Database Layer                                │
│  ClickHouse │ MySQL │ PostgreSQL │ Doris │ ...                  │
└─────────────────────────────────────────────────────────────────┘
```

## 2.2 数据流

```
用户问题
   ↓
LLM Agent (含 RAG 上下文注入)
   ↓
DSL (JSON) — Pydantic 校验
   ↓
Semantic Layer — 指标展开、维度解析
   ↓
Permission Layer — 行级/列级权限注入
   ↓
Query Planner — 优化路由、Join 推导
   ↓
SQLAlchemy — 构建标准 SQL 表达式
   ↓
sqlglot — 方言转换 (MySQL/PostgreSQL/ClickHouse/Doris)
   ↓
数据库执行
   ↓
结果格式化 + 脱敏 + 审计日志
```

## 2.3 项目目录结构

```
nl2dsl/
├── nl2dsl/
│   ├── __init__.py
│   ├── api.py               # FastAPI 应用入口
│   ├── config.py            # 配置管理 (Pydantic Settings)
│   ├── dsl/
│   │   ├── __init__.py
│   │   ├── models.py        # Pydantic DSL 模型
│   │   ├── validator.py     # DSL 校验器
│   │   └── builder.py       # DSL 构建辅助工具
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── prompts.py       # Prompt 模板
│   │   └── client.py        # LLM API 客户端封装
│   ├── graph/               # LangGraph StateGraph 查询管道
│   │   ├── state.py         # QueryState TypedDict（含 Annotated reducer）
│   │   ├── nodes.py         # 所有节点函数
│   │   ├── edges.py         # 条件路由函数
│   │   ├── subgraphs.py     # 权限检查子图 + 验证子图
│   │   └── builder.py       # StateGraph 组装
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── base.py          # 向量存储抽象基类
│   │   ├── store.py         # Milvus Lite / Milvus Server 实现
│   │   ├── embedder.py      # 文本嵌入
│   │   ├── retriever.py     # 检索逻辑
│   │   └── sync.py          # 配置驱动的启动自检同步
│   ├── permission/
│   │   ├── __init__.py
│   │   ├── models.py        # 权限模型
│   │   ├── row_level.py     # 行级权限注入
│   │   └── column_level.py  # 列级权限控制
│   ├── planner/
│   │   ├── __init__.py
│   │   ├── optimizer.py     # 查询优化规则
│   │   └── router.py        # 路由决策
│   ├── semantic/
│   │   ├── __init__.py
│   │   ├── registry.py      # 指标/维度注册中心
│   │   └── resolver.py      # 指标展开、Join 推导
│   ├── sql_engine/
│   │   ├── __init__.py
│   │   ├── builder.py       # SQLAlchemy 表达式构建
│   │   ├── dialect.py       # sqlglot 方言转换
│   │   ├── executor.py      # 数据库连接与执行
│   │   └── metadata.py      # 数据库元数据提取
│   ├── audit/
│   │   ├── __init__.py
│   │   └── logger.py        # 审计日志记录
│   ├── feedback/
│   │   ├── __init__.py
│   │   └── collector.py     # 反馈收集与学习
│   ├── engine.py            # 引擎入口（多域发现 + 插件加载 + 默认组件注册）
│   ├── domain_context.py    # 每域组件容器（DomainContext）
│   ├── plugin.py            # 插件框架（Registry + Pipeline + Plugin ABC）
│   └── protocols.py         # 组件 Protocol 定义
│
examples/
└── plugins/
    └── ollama_plugin.py     # 示例：Ollama LLM 后端插件

├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── configs/
│   ├── metrics.yaml         # 指标定义
│   ├── schema.yaml          # 表结构定义
│   └── permissions.yaml     # 权限配置
├── scripts/
│   └── init_vector_store.py # 初始化向量库
├── docker-compose.yml       # 依赖服务（可选 Milvus Server）
├── pyproject.toml           # 项目配置
└── README.md
```
