# NL2DSL 多领域支持设计文档

## 背景

NL2DSL 当前只支持单一业务领域（电商订单）。新增银行零售业务后，需要同时支持多套业务语义、数据库和 RAG 向量库，且新增领域时尽量不修改代码。

## 设计目标

1. **零配置**：新增领域只需放 YAML + 运行数据生成脚本，无需改代码或配环境变量
2. **向后兼容**：现有 API 不传 `domain` 时行为完全一致
3. **资源共享**：BGE 向量模型、LLMClient 全局只加载一次
4. **完全隔离**：每个领域有自己的数据库、语义配置、RAG 向量库

## 架构总览

```
API Layer
  POST /api/v1/query {domain: "bank", question: "..."}
         │
         ▼
Engine (单例)
  ┌─────────────────────────────────────────────┐
  │ Shared Components (全局共享)                 │
  │ • LLMClient                                 │
  │ • BGEEmbedder (~400MB，只加载一次)          │
  │ • InMemorySaver                             │
  └─────────────────────────────────────────────┘
         │
    ┌────┴────┐
    ▼         ▼
 DomainCtx  DomainCtx
(ecommerce)  (bank)
  • registry   • registry
  • validator  • validator
  • sql_builder• sql_builder
  • sandbox    • sandbox
  • executor   • executor
  • rag        • rag
  • graph      • graph
```

## 核心设计

### DomainContext

所有领域共用同一个 dataclass，实例化时传入不同参数：

```python
@dataclass
class DomainContext:
    domain: str
    registry_dict: dict
    validator: DSLValidator
    resolver: SemanticResolver
    sql_builder: SQLBuilder
    sandbox: QuerySandbox
    executor: SQLExecutor
    row_security: RowLevelSecurity
    col_security: ColumnLevelSecurity
    rag_retriever: RAGRetriever | None
    graph: CompiledGraph
```

### 领域自动发现

Engine 启动时扫描 `configs/` 目录：

```python
def _discover_domains(config_dir: Path) -> list[str]:
    domains = []
    # 默认领域（无前缀的 metrics.yaml）
    if (config_dir / "metrics.yaml").exists():
        domains.append("ecommerce")
    # 其他领域（*_metrics.yaml）
    for f in config_dir.glob("*_metrics.yaml"):
        prefix = f.name.replace("_metrics.yaml", "")
        if prefix:
            domains.append(prefix)
    return domains
```

**新增一个领域只需两步：**
1. 在 `configs/` 下放 `{domain}_metrics.yaml` + `{domain}_terms.yaml` + `{domain}_history.yaml`
2. 运行 `python scripts/generate_{domain}_data.py`

### 数据库与向量库自动命名

| 领域 | SQLite DB | Milvus URI |
|------|-----------|------------|
| ecommerce | `sqlite:///./nl2dsl.db` | `./milvus_lite.db` |
| bank | `sqlite:///./bank.db` | `./bank_milvus_lite.db` |
| xxx | `sqlite:///./xxx.db` | `./xxx_milvus_lite.db` |

```python
def _get_db_url(domain: str) -> str:
    if domain == "ecommerce":
        return settings.db_url
    return f"sqlite:///./{domain}.db"

def _get_milvus_uri(domain: str) -> str:
    if domain == "ecommerce":
        return settings.milvus_uri
    return f"./{domain}_milvus_lite.db"
```

### Engine 初始化流程

对每个发现的 domain：
1. 加载 `{domain}_metrics.yaml`（默认无前缀）→ SemanticRegistry
2. 加载 `{domain}_permissions.yaml`（如有）
3. 创建 DB Engine → `sqlite:///./{domain}.db`
4. 创建 Validator / Resolver / Scanner
5. 创建 SQLBuilder(db_engine, table_map)
6. 创建 Sandbox / Executor
7. 创建 RowSecurity / ColSecurity
8. 创建 RAGRetriever（共享 BGEEmbedder + 独立 Milvus 文件）
9. 调用 `build_graph()` 绑定所有组件 → CompiledGraph
10. 封装为 DomainContext，存入 `Engine._domains[domain]`

## API 设计

### QueryRequest

```python
class QueryRequest(BaseModel):
    question: str
    domain: str = "ecommerce"   # 新增，向后兼容
    user_id: str
    tenant_id: str
```

### 路由改造

```python
@app.post("/api/v1/query")
async def query(req: QueryRequest):
    ctx = _nl2dsl_engine.get_domain(req.domain)
    state = QueryState(question=req.question, domain=req.domain, ...)
    result = await ctx.graph.ainvoke(state)
    return {"status": "success", "data": result["data"]}
```

### Schema/Metrics 路由

```python
@app.get("/api/v1/schema")
async def get_schema(domain: str = Query(default="ecommerce")):
    ctx = _nl2dsl_engine.get_domain(domain)
    return ctx.registry_dict
```

### Graph State

```python
class QueryState(TypedDict):
    question: str
    domain: str               # 新增
    user_id: str
    tenant_id: str
    # ... 其他字段不变
```

## 文件改动清单

| 文件 | 改动 | 优先级 |
|------|------|--------|
| `nl2dsl/engine.py` | 大改：DomainContext + 多领域发现 + 循环初始化 | P0 |
| `nl2dsl/api.py` | 改：QueryRequest 加 domain，路由取 DomainContext，Schema 路由加 domain 参数 | P0 |
| `nl2dsl/graph/state.py` | 加 `domain` 字段 | P0 |
| `nl2dsl/rag/sync.py` | 改：auto_sync 支持 per-domain Milvus URI | P0 |
| `scripts/generate_bank_data.py` | 改：默认输出 `bank.db` | P1 |
| `.env.example` | 删：去掉 NL2DSL_DOMAIN | P1 |
| `nl2dsl/config.py` | 删：去掉 `domain` 配置项（不再需要） | P1 |

## 向后兼容

- 所有 API 的 `domain` 参数默认值为 `"ecommerce"`
- 不传 `domain` 时行为与当前完全一致
- 现有客户端无需任何改动
- `configs/metrics.yaml`（无前缀）继续作为默认领域配置

## 错误处理

- 请求传入不存在的 domain → 返回 400，提示可用领域列表
- 某个领域配置缺失（如只有 metrics 没有 terms）→ 启动时 warning，该领域降级运行（RAG 可能不完整）
- 某个领域数据库不存在 → SQLBuilder 初始化时报错（和当前行为一致）

## 测试策略

- 单元测试：验证 `_discover_domains` 正确扫描
- 集成测试：同时加载 ecommerce + bank，验证请求能路由到正确领域
- E2E 测试：分别对两个领域发送查询，验证返回结果来自正确的数据库
