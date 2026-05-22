# NL2DSL Engine

> 企业级自然语言到 DSL 智能问数引擎
>
> **AI 负责语义理解，系统负责执行治理**

## 项目简介

NL2DSL Engine 是一个企业级智能问数系统。与传统 NL2SQL 不同，本系统采用**分层架构**，LLM 只负责生成结构化 DSL（JSON），由系统负责校验、权限控制、语义解析和 SQL 构建。

```
自然语言 → LLM → DSL → 校验 → 权限注入 → 语义解析 → SQLAlchemy → 标准 SQL → 执行
```

这样做的好处：SQL 可校验、权限可控、查询可优化、多数据库方言可适配。

## 核心特性

- **分层架构**：LLM 生成 DSL，系统编译为 SQL，解耦语义理解与执行
- **LangGraph 管道**：基于 StateGraph 的查询链路，支持条件分支、检查点、流式输出
- **语义层**：YAML 配置统一管理指标和维度，禁止直接引用数据库原始字段
- **权限治理**：行级权限自动注入 + 列级权限控制 + 脱敏规则
- **安全扫描**：SQL 执行前多阶段安全校验
- **人工审核**：高风险查询自动中断，等待人工确认后继续
- **审计追踪**：完整记录查询全链路，支持 LangSmith 追踪
- **双模式生成**：LLM 优先，未配置时自动回退到关键词匹配（Mock）

## 技术栈

| 层级 | 技术 |
|------|------|
| Web 框架 | FastAPI |
| 工作流引擎 | LangGraph (StateGraph) |
| LLM 接入 | LangChain + OpenAI SDK（支持通义千问等兼容接口） |
| SQL 构建 | SQLAlchemy Core + sqlglot |
| 向量存储 | Milvus Lite |
| 配置管理 | Pydantic Settings + YAML |

## 快速开始

### 环境要求

- Python 3.10+

### 安装依赖

```bash
pip install -e ".[dev]"
```

### 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入 LLM API Key
```

### 启动服务

```bash
uvicorn nl2dsl.api:app --reload --host 0.0.0.0 --port 8000
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
```

## 项目结构

```
nl2dsl/
├── api.py              # FastAPI 应用入口
├── api_factory.py      # App 工厂（用于测试注入）
├── config.py           # 配置管理（Pydantic Settings）
├── dsl/                # DSL 模型、校验器、构建工具
├── graph/              # LangGraph StateGraph 查询管道（核心链路）
├── llm/                # LLM 客户端 + Prompt 模板
├── rag/                # 向量存储（Milvus Lite）
├── permission/         # 行级/列级权限控制
├── semantic/           # 语义层注册中心（YAML 加载）
├── sql_engine/         # SQLAlchemy Core 构建 + 安全扫描
├── audit/              # 审计日志
├── feedback/           # 用户纠错反馈
└── utils/              # 统一日志配置

tests/
├── unit/               # 单元测试
├── integration/        # 集成测试
└── e2e/                # 端到端测试

configs/
├── metrics.yaml        # 指标/维度/数据源定义
└── permissions.yaml    # 权限规则配置
```

## 查询链路

```
用户请求
  → API 层（提取 user_id/tenant_id，构建 QueryState）
  → LangGraph StateGraph:
    → clarification       歧义检测
    → validation 子图     DSL 生成 → 校验 → 自动修正循环
    → permission_check    行级权限注入 + 列级权限检查
    → resolve_semantic    指标名 → SQL 表达式
    → build_sql           SQLAlchemy Core 构建
    → scan_sql            安全扫描
    → sandbox_check       沙箱预检
      → 不通过 → human_review（人工审核）
    → execute_sql         数据库执行
      → 失败 → simplify_dsl → 重试
  → 审计日志记录
  → 返回响应
```

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
| GET | `/api/v1/admin/audit/queries` | 查询审计日志 |

## 核心设计决策

**为什么 LLM 只生成 DSL 不生成 SQL？**
- DSL 是结构化 JSON，可校验、可修正
- SQL 是自由文本，出错后难以定位修复
- DSL 层级可做权限控制和查询优化

**为什么使用 LangGraph StateGraph？**
- 原生支持条件分支（校验失败修正、人工审核）
- 检查点支持流程中断和恢复
- `astream` 实时推送每个节点结果
- LangSmith 自动追踪完整链路

## 开发规范

```bash
# 格式化
ruff format .

# Lint
ruff check .

# 类型检查
mypy --strict

# 测试
pytest
pytest --cov=nl2dsl --cov-report=html
```

## License

MIT
