# NL2DSL Engine

> 企业级自然语言到 DSL 智能问数引擎
>
> **AI 负责语义理解，系统负责执行治理**

## 项目定位

**NL2DSL 本质上是一个数据治理的消费层。**

它的可用性和准确性完全取决于底层数据治理的完善程度。没有完善的数据治理，NL2DSL 就像没有地基的房子——LLM 无法理解混乱的表结构、生成的 SQL 会频繁报错、权限控制存在漏洞、用户得到的结果不可信。

### 架构分层

```
┌─────────────────────────────────────────────┐
│  NL2DSL 消费层（本项目）                      │
│  - 自然语言理解（LLM）                        │
│  - DSL 生成与校验                             │
│  - 查询执行与结果返回                          │
│  - 审计追踪与反馈收集                          │
└─────────────────────────────────────────────┘
                      ↑ 消费
┌─────────────────────────────────────────────┐
│  数据治理服务层（前置依赖）                     │
│  - 指标注册中心（metrics.yaml）               │
│  - 维度注册中心（dimensions.yaml）            │
│  - 数据源注册中心（data_sources.yaml）        │
│  - 权限策略中心（permissions.yaml）           │
│  - 敏感数据目录（sensitive_columns）          │
│  - 数据血缘关系（joins / 表关联）             │
└─────────────────────────────────────────────┘
                      ↑ 消费
┌─────────────────────────────────────────────┐
│  数据存储层                                   │
│  - 物理数据库（SQLite / MySQL / ...）         │
│  - 向量数据库（Milvus）                       │
│  - 审计日志库                                 │
└─────────────────────────────────────────────┘
```

### 与传统 NL2SQL 的区别

传统 NL2SQL 让 LLM 直接生成 SQL，存在三大问题：
1. **不可校验** — SQL 是自由文本，出错后难以定位修复
2. **不可控** — 权限、安全、优化无法干预
3. **不可信** — LLM 对物理表结构的理解容易出错

NL2DSL 采用**分层架构**：LLM 只负责生成结构化 DSL（JSON），由系统基于数据治理定义负责校验、权限控制、语义解析和 SQL 构建。

```
自然语言 → RAG 检索 → LLM → DSL → 校验 → 权限注入 → 语义解析 → SQLAlchemy → 标准 SQL → 执行
```

这样做的好处：SQL 可校验、权限可控、查询可优化、多数据库方言可适配。**但前提是底层数据治理已经完备。**

## 核心特性

### 作为数据治理消费层

- **治理定义消费**：指标、维度、数据源、权限全部从 YAML 治理配置读取，不内置任何业务定义
- **语义层隔离**：用户和 LLM 只接触语义名称（`sales_amount`、`region`），物理字段（`SUM(pay_amount)`、`region_code`）由治理层映射
- **权限自动生效**：行级过滤、列级控制、数据脱敏全部基于治理配置自动注入，无需代码改动
- **血缘感知 JOIN**：表关联关系从 `data_sources.*.joins` 治理配置读取，支持精确 JOIN 检测（只 JOIN 被引用的表）

### 系统能力

- **分层架构**：LLM 生成 DSL，系统编译为 SQL，解耦语义理解与执行
- **LangGraph 管道**：基于 StateGraph 的查询链路，支持条件分支、检查点、流式输出
- **RAG 驱动**：基于 BGE 中文向量模型 + Milvus Lite，4 集合（schema/metrics/terms/history）混合检索
- **启动自检同步**：YAML 配置改动后重启自动同步到向量库，无需手动跑脚本
- **多域支持**：自动发现 `configs/` 下多个业务域（如 `bank_metrics.yaml`），每个域独立 DB + Milvus + RAG
- **Agentic 节点**：decompose（复杂查询改写）、correct_dsl（定向 RAG 修正）、verify_dsl（执行后自检）
- **配置驱动语义**：业务术语 / 历史示例通过 YAML 维护，业务人员可改
- **插件框架**：组件可插拔（Registry）+ 节点可扩展（Pipeline 钩子）
- **安全扫描**：SQL 执行前多阶段安全校验
- **人工审核**：高风险查询自动中断，等待人工确认后继续
- **审计追踪**：完整记录查询全链路，含 trace 信息
- **前端工作台**：React + AntD + ECharts，含查询页和管理后台

## 技术栈

| 层级 | 技术 |
|------|------|
| Web 框架 | FastAPI |
| 工作流引擎 | LangGraph (StateGraph) |
| LLM 接入 | OpenAI SDK 兼容接口（默认智谱 GLM-4.5-Air，可切 Ollama / 通义千问） |
| SQL 构建 | SQLAlchemy Core + sqlglot |
| 向量存储 | Milvus Lite |
| 向量模型 | BGE-base-zh-v1.5（本地） |
| 配置管理 | Pydantic Settings + YAML |
| 前端 | React + Vite + AntD + ECharts + Playwright |

## 数据治理前置条件

NL2DSL **不是数据治理的替代品，而是数据治理的放大器**。在部署 NL2DSL 之前，必须确保以下治理体系已经建立：

### 1. 指标治理（必须）

所有业务指标必须在 `metrics.yaml` 中注册：

```yaml
metrics:
  sales_amount:
    expr: SUM(pay_amount)          # 物理计算式
    description: "销售额"           # LLM 理解的业务含义
```

**没有治理的后果**：同一个概念多个定义（`sales_amount` vs `revenue` vs `营业额`）→ LLM 随机选择 → 结果不一致。

### 2. 维度治理（必须）

所有维度必须在 `dimensions.yaml` 中注册，含物理映射：

```yaml
dimensions:
  region:
    column: region_code            # 物理字段名
    description: "地区"
    value_map:                     # 语义值 → 物理值
      "华东": "HD"
      "华南": "HN"
```

**没有治理的后果**：`value_map` 不完整 → 用户查"华中"返回空结果；`column` 映射错误 → SQL 引用不存在的列。

### 3. 数据源治理（必须）

所有数据源及其 JOIN 关系必须在 `data_sources.yaml` 中注册：

```yaml
data_sources:
  orders:
    table: order_fact
    metrics: [sales_amount, gmv, ...]
    dimensions: [product_name, category, ...]
    joins:
      product_dim:
        on: product_id
        type: left
        alias: p
```

**没有治理的后果**：JOIN 关系未注册 → 多表查询失败；ON 条件错误 → 笛卡尔积。

### 4. 数据安全治理（必须）

敏感字段、脱敏规则、用户权限必须在 `permissions.yaml` 中定义：

```yaml
sensitive_columns:
  cust_nm:
    level: "high"

masking_rules:
  cust_nm: "{x[0]}**"

users:
  u001:
    tenant_id: "t001"
    row_filters:
      org_name:
        operator: "in"
        value: ["北京分行"]
    allowed_dimensions: [customer_name, ...]
```

**没有治理的后果**：敏感数据裸奔；租户间数据隔离失效。

### 5. 成熟度评估

| 数据治理成熟度 | NL2DSL 效果 |
|-------------|-----------|
| **完善**（指标/维度/权限全部标准化） | 体验极佳：自然语言准确翻译、权限自动生效、结果可信 |
| **部分**（有定义但不完整） | 可用但风险高：LLM 幻觉增加、查询偶尔失败、权限有漏洞 |
| **缺失**（无治理，直接查物理表） | **不可用**：LLM 不理解表结构、SQL 错误率高、安全风险极大 |

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+（前端）
- torch >= 2.6（sentence-transformers 强制要求）

### 安装依赖

```bash
# 后端
pip install -r requirements.txt

# 前端
cd web && npm install
```

### 配置环境变量

复制 `.env.example` 为 `.env` 并填入 LLM 配置：

```bash
# 智谱 AI（默认）
NL2DSL_LLM_API_KEY=your-zhipu-api-key
NL2DSL_LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
NL2DSL_LLM_MODEL=glm-4.5-air

# 或 Ollama 本地
# NL2DSL_LLM_API_KEY=ollama
# NL2DSL_LLM_BASE_URL=http://localhost:11434/v1
# NL2DSL_LLM_MODEL=qwen3:8b
```

### 启动服务

```bash
# 后端（首次启动自动检测 YAML mtime 并同步到向量库）
uvicorn nl2dsl.api:app --reload --host 0.0.0.0 --port 8000

# 前端
cd web && npm run dev
```

访问：
- 后端 API：http://localhost:8000
- 前端工作台：http://localhost:5173

### 验证服务

```bash
# Health 检查
curl http://localhost:8000/health

# 自然语言查询
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "查询华东地区销售额最高的 10 个产品",
    "domain": "ecommerce",
    "user_id": "u001",
    "tenant_id": "t001"
  }'

# 调试 RAG 检索内容
curl "http://localhost:8000/api/v1/debug/rag?q=各品牌的流水&domain=ecommerce"
```

## 项目结构

```
nl2dsl/
├── __init__.py             # 导出 Engine, Plugin
├── api.py                  # FastAPI 应用入口
├── api_factory.py          # App 工厂（用于测试注入）
├── config.py               # 配置管理（Pydantic Settings）
├── engine.py               # 引擎入口：插件加载 + 默认组件注册 + RAG 启动自检
├── plugin.py               # 插件框架：Registry + Pipeline + Plugin ABC
├── protocols.py            # 组件 Protocol 定义
├── dsl/                    # DSL 模型、校验器、构建工具
├── graph/                  # LangGraph StateGraph 查询管道（核心链路）
├── llm/                    # LLM 客户端 + Prompt 模板
├── rag/                    # 向量存储 + 检索器 + 启动自检同步
│   ├── store.py            # Milvus Lite 封装
│   ├── embedder.py         # BGE 中文向量模型
│   ├── retriever.py        # 混合检索（schema/metrics/terms 走 jieba，history 走整句）
│   └── sync.py             # 配置驱动的启动自检同步
├── permission/             # 行级/列级权限控制
├── semantic/               # 语义层注册中心（YAML 加载）
├── sql_engine/             # SQLAlchemy Core 构建 + 安全扫描 + 沙箱
├── audit/                  # 审计日志
├── feedback/               # 用户纠错反馈
└── utils/                  # 统一日志配置

configs/
├── metrics.yaml            # 指标/维度/数据源定义 → 同步到 schema + metrics 集合
├── terms.yaml              # 业务术语 + 别名（"流水"→gmv 等）→ 同步到 terms 集合
├── history.yaml            # 历史"问题→DSL"示例 → 同步到 history 集合
└── permissions.yaml        # 权限规则配置

web/                        # React 前端
├── src/
│   ├── pages/              # QueryPage（查询工作台）、AdminPage（管理后台）
│   ├── components/         # 查询/管理后台组件
│   ├── api/                # axios 客户端（超时 120s 兼容慢 LLM）
│   └── hooks/              # React Query hooks
└── tests/e2e/              # Playwright 端到端测试

scripts/
├── init_vector_store.py    # 手动初始化向量库（可选，启动自检通常已覆盖）
└── test_rag_coverage.py    # RAG 4 集合覆盖度测试

tests/
├── unit/                   # 单元测试
├── integration/            # 集成测试
└── e2e/                    # 端到端测试

data/                       # 数据文件目录（自动创建，不受 cwd 影响）
├── nl2dsl.db               # SQLite 业务数据 + 审计日志
├── milvus_lite.db/         # 向量库数据目录
├── bank.db                 # 多域：bank 域业务数据
├── bank_milvus_lite.db/    # 多域：bank 域向量库
└── .ecommerce_rag_sync_state.json  # RAG 同步状态
```

## 插件使用

```python
from nl2dsl import Engine, Plugin

# 方式1：零配置开箱即用
engine = Engine()
app = engine.build_fastapi_app()

# 方式2：用插件扩展（如替换 LLM 后端）
class OllamaPlugin(Plugin):
    def register(self, engine):
        engine.register("llm", OllamaLLM(model="qwen3:8b"))

engine = Engine()
engine.use(OllamaPlugin())
app = engine.build_fastapi_app()
```

## 查询链路

```
用户请求
  → API 层（提取 user_id/tenant_id/domain，构建 QueryState）
  → LangGraph StateGraph:
    → clarification         歧义检测
    → decompose             复杂查询改写（对比/同比/趋势 → 单 DSL）
    → validation 子图       RAG 检索 → LLM 生成 DSL → 校验 → 修正循环
    → permission_check      行级权限注入 + 列级权限检查
    → resolve_semantic      指标名 → SQL 表达式
    → build_sql             SQLAlchemy Core 构建
    → scan_sql              安全扫描
    → sandbox_check         沙箱预检
      → 不通过 → human_review（人工审核）
    → execute_sql           数据库执行
      → 失败 → simplify_dsl → 重试
    → verify_dsl            执行后 LLM 自检（warning-only）
  → 审计日志记录
  → 返回响应
```

## RAG 设计

4 个 Milvus 集合，按用途采用不同检索策略：

| 集合 | 来源 YAML | 内容 | 检索方式 |
|------|---------|------|----------|
| `schema` | metrics.yaml | 维度 + 指标定义 + join 关系 | jieba 切词关键词检索 |
| `metrics` | metrics.yaml | 指标计算式 | jieba 切词关键词检索 |
| `terms` | terms.yaml | 业务术语 + 别名（"流水→gmv"）| jieba 切词关键词检索 |
| `history` | history.yaml | "问题→DSL"示例 | **整句语义检索**（找最像的） |

**Join 关系同步**：`metrics.yaml` 中 `data_sources.*.joins` 的配置会自动同步到 schema 集合，RAG prompt 中显式展示表关联关系，LLM 据此在 DSL 中正确填充 `joins` 字段。

**自检同步机制**：后端启动时对比每个 YAML 的 mtime 和 `.rag_sync_state.json` 中的记录，过期则增量重灌；都最新则跳过 BGE 模型加载，启动毫秒级返回。多域场景下每个域有独立的 sync state 文件。

修改 YAML 后只需重启后端，无需手动跑脚本。

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/api/v1/query` | 自然语言查询 |
| POST | `/api/v1/query/dsl` | 仅生成 DSL |
| POST | `/api/v1/query/execute` | 直接执行 DSL |
| POST | `/api/v1/query/stream` | 流式查询（SSE） |
| POST | `/api/v1/query/resume` | 恢复中断流程 |
| GET | `/api/v1/schema` | 获取语义层 Schema（支持 `?domain=`） |
| GET | `/api/v1/metrics` | 获取指标列表（支持 `?domain=`） |
| POST | `/api/v1/feedback` | 提交纠错反馈 |
| GET | `/api/v1/admin/audit/queries` | 查询审计日志列表 |
| GET | `/api/v1/admin/audit/queries/{id}` | 查询审计日志详情 |
| GET | `/api/v1/debug/rag?q=...` | 调试：查看 RAG 检索结果（支持 `?domain=`） |

## 核心设计决策

**为什么 LLM 只生成 DSL 不生成 SQL？**
- DSL 是结构化 JSON，可校验、可修正
- SQL 是自由文本，出错后难以定位修复
- DSL 层级可做权限控制和查询优化

**为什么使用 LangGraph StateGraph？**
- 原生支持条件分支（校验失败修正、人工审核）
- 检查点支持流程中断和恢复
- `astream` 实时推送每个节点结果
- 子图封装让权限/校验逻辑独立

**为什么 RAG 不全部走整句语义检索？**
- `schema`/`metrics`/`terms` 是**短命名实体**（"brand"、"流水→gmv"），jieba 关键词精确匹配更准
- `history` 是**完整问句**，整句语义检索能找到表达相似但用词不同的示例
- 分而治之比一刀切效果更好

**为什么 NL2DSL 不做数据治理本身？**

就像 **Tableau / PowerBI** 不定义什么是"销售额"，而是消费数据仓库中定义的度量一样：

| 层级 | 职责 | 示例 |
|------|------|------|
| 数据治理层 | 定义业务语义、管理数据质量、控制访问权限 | `metrics.yaml`、`permissions.yaml` |
| NL2DSL 消费层 | 理解用户意图、匹配治理定义、生成并执行查询 | LLM → DSL → SQL |

数据治理是**组织级能力**，需要业务、数据、安全团队共建；NL2DSL 是**技术层能力**，在治理完备的前提下提供自然语言接口。两者是上下游关系，不是替代关系。

## License

MIT
