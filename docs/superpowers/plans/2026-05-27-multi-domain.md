# NL2DSL 多领域支持实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 NL2DSL 从单领域架构改造为支持多领域（ecommerce + bank + 未来可扩展），通过自动扫描 configs 目录发现领域配置，每个领域有独立的 DB + 语义层 + RAG 向量库。

**Architecture:** Engine 单例初始化时扫描 configs 目录自动发现所有领域，为每个领域创建 DomainContext（含 registry、validator、sql_builder、rag_retriever、CompiledGraph 等）。BGE 向量模型和 LLMClient 全局共享。API 请求通过 `domain` 参数路由到对应的 DomainContext。

**Tech Stack:** Python 3.10+, FastAPI, LangGraph, SQLAlchemy, Milvus Lite, BGE Embedder

---

## 文件结构

| 文件 | 操作 | 说明 |
|------|------|------|
| `nl2dsl/domain_context.py` | 新建 | DomainContext dataclass |
| `nl2dsl/config.py` | 修改 | 删掉 `domain` 配置项 |
| `nl2dsl/engine.py` | 大改 | DomainContext + 多领域发现 + 循环初始化 |
| `nl2dsl/graph/state.py` | 修改 | 加 `domain` 字段 |
| `nl2dsl/api.py` | 大改 | QueryRequest 加 domain，路由取 DomainContext，剥离 mock 数据 |
| `nl2dsl/rag/sync.py` | 修改 | auto_sync 支持 per-domain Milvus URI |
| `scripts/generate_bank_data.py` | 修改 | 默认输出改为 `bank.db` |
| `scripts/seed_ecommerce_data.py` | 新建 | 从 api.py 剥离的电商 mock 数据插入脚本 |
| `.env.example` | 修改 | 删掉 `NL2DSL_DOMAIN` |
| `tests/unit/test_domain_discovery.py` | 新建 | 领域发现单元测试 |

---

### Task 1: DomainContext dataclass

**Files:**
- Create: `nl2dsl/domain_context.py`
- Test: `tests/unit/test_domain_discovery.py` (先写骨架)

- [ ] **Step 1: 创建 DomainContext dataclass**

Create `nl2dsl/domain_context.py`:

```python
"""Domain context: per-domain container for all pipeline components."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DomainContext:
    """All components needed to execute a query for a single domain.

    Each domain gets its own database, semantic registry, validator,
    SQL builder, sandbox, executor, and RAG retriever.
    LLM client and embedder are shared across domains.
    """

    domain: str
    registry_dict: dict
    validator: "DSLValidator"
    resolver: "SemanticResolver"
    sql_builder: "SQLBuilder"
    sandbox: "QuerySandbox"
    executor: "SQLExecutor"
    row_security: "RowLevelSecurity"
    col_security: "ColumnLevelSecurity"
    rag_retriever: "RAGRetriever | None"
    graph: "CompiledGraph"
```

- [ ] **Step 2: Commit**

```bash
git add nl2dsl/domain_context.py
git commit -m "feat(domain): add DomainContext dataclass"
```

---

### Task 2: 修改 config.py — 删掉 domain 配置项

**Files:**
- Modify: `nl2dsl/config.py`

- [ ] **Step 1: 删掉 `domain` 配置项**

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="NL2DSL_",
    )

    llm_api_key: str = ""
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4/"
    llm_model: str = "glm-4.5-air"

    # REMOVED: domain config (now auto-discovered from configs/ dir)

    db_url: str = "sqlite:///./nl2dsl.db"
    max_limit: int = 10000
    query_timeout: int = 30

    vector_store_type: str = "milvus_lite"
    milvus_uri: str = "./milvus_lite.db"
    milvus_host: str = "localhost"
    milvus_port: int = 19530
```

- [ ] **Step 2: Commit**

```bash
git add nl2dsl/config.py
git commit -m "refactor(config): remove domain setting (now auto-discovered)"
```

---

### Task 3: 修改 engine.py — 核心大改

**Files:**
- Modify: `nl2dsl/engine.py`
- Test: `tests/unit/test_domain_discovery.py`

- [ ] **Step 1: 写领域发现测试**

```python
# tests/unit/test_domain_discovery.py
from pathlib import Path

from nl2dsl.engine import Engine


def test_discover_domains_finds_default():
    """Default ecommerce domain is found when metrics.yaml exists."""
    engine = Engine()
    assert "ecommerce" in engine.domains


def test_discover_domains_finds_bank():
    """Bank domain is found when bank_metrics.yaml exists."""
    engine = Engine()
    assert "bank" in engine.domains


def test_get_domain_returns_context():
    """get_domain returns a DomainContext with correct registry."""
    engine = Engine()
    ctx = engine.get_domain("bank")
    assert ctx.domain == "bank"
    assert "total_balance" in ctx.registry_dict["metrics"]


def test_get_domain_fallback_to_default():
    """Unknown domain falls back to ecommerce."""
    engine = Engine()
    ctx = engine.get_domain("nonexistent")
    assert ctx.domain == "ecommerce"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_domain_discovery.py -v
```

Expected: FAIL (Engine 还没有 `domains` 属性和 `get_domain` 方法)

- [ ] **Step 3: 重写 engine.py**

Replace the entire `nl2dsl/engine.py` with:

```python
"""NL2DSL Engine entry point with multi-domain support."""

from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine

from nl2dsl.config import settings
from nl2dsl.domain_context import DomainContext
from nl2dsl.plugin import Registry, Pipeline, Plugin
from nl2dsl.graph.builder import build_graph
from nl2dsl.utils.logger import get_logger

logger = get_logger("engine")


def _discover_domains(config_dir: Path) -> list[str]:
    """Scan configs/ directory to discover all domains.

    Rules:
    - metrics.yaml (no prefix) -> domain="ecommerce"
    - xxx_metrics.yaml -> domain="xxx"
    """
    domains = []
    if (config_dir / "metrics.yaml").exists():
        domains.append("ecommerce")

    for f in config_dir.glob("*_metrics.yaml"):
        prefix = f.name.replace("_metrics.yaml", "")
        if prefix and prefix not in domains:
            domains.append(prefix)

    logger.info("Discovered domains: %s", domains)
    return domains


def _get_db_url(domain: str) -> str:
    """Auto-name database files per domain."""
    if domain == "ecommerce":
        return settings.db_url
    return f"sqlite:///./{domain}.db"


def _get_milvus_uri(domain: str) -> str:
    """Auto-name Milvus files per domain."""
    if domain == "ecommerce":
        return settings.milvus_uri
    return f"./{domain}_milvus_lite.db"


class Engine:
    def __init__(self):
        self._domains: dict[str, DomainContext] = {}
        self._plugins: list[Plugin] = []
        self._built = False
        self._checkpointer = InMemorySaver()
        self._load_defaults()

    @property
    def domains(self) -> list[str]:
        return list(self._domains.keys())

    def get_domain(self, domain: str) -> DomainContext:
        """Get DomainContext for a domain. Falls back to ecommerce."""
        if domain in self._domains:
            return self._domains[domain]
        logger.warning("Domain '%s' not found, falling back to ecommerce", domain)
        return self._domains.get("ecommerce")

    def use(self, plugin: Plugin) -> "Engine":
        self._plugins.append(plugin)
        return self

    def register(self, name: str, component) -> "Engine":
        # For backward compatibility: store in a default registry
        if not hasattr(self, "_legacy_registry"):
            self._legacy_registry = Registry()
        self._legacy_registry.register(name, component)
        return self

    def build(self):
        if self._built:
            raise RuntimeError("Engine.build() can only be called once")
        for plugin in sorted(self._plugins, key=lambda p: p.priority):
            logger.info("Loading plugin: %s (priority=%d)", plugin.name, plugin.priority)
            plugin.register(self)
        self._built = True

    def build_fastapi_app(self) -> FastAPI:
        self.build()
        app = FastAPI(title="NL2DSL", version="0.1.0")
        return app

    def _load_defaults(self):
        from nl2dsl.semantic.registry import SemanticRegistry
        from nl2dsl.semantic.resolver import SemanticResolver
        from nl2dsl.dsl.validator import DSLValidator
        from nl2dsl.sql_engine.builder import SQLBuilder
        from nl2dsl.sql_engine.scanner import SQLScanner
        from nl2dsl.sql_engine.executor import SQLExecutor
        from nl2dsl.permission.row_level import RowLevelSecurity
        from nl2dsl.permission.column_level import ColumnLevelSecurity
        from nl2dsl.query.sandbox import QuerySandbox
        from nl2dsl.query.clarification import ClarificationDetector
        from nl2dsl.llm.client import LLMClient
        from nl2dsl.llm.prompts import DSL_SYSTEM_PROMPT
        from nl2dsl.rag.store import MilvusLiteStore
        from nl2dsl.rag.embedder import BGEEmbedder
        from nl2dsl.rag.retriever import RAGRetriever
        from nl2dsl.rag.sync import auto_sync

        config_dir = Path(__file__).parent.parent / "configs"
        discovered = _discover_domains(config_dir)

        if not discovered:
            logger.warning("No domains discovered in %s", config_dir)
            return

        # Shared components (initialized once)
        llm = None
        embedder = None
        if settings.llm_api_key:
            llm = LLMClient(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                model=settings.llm_model,
            )
            try:
                embedder = BGEEmbedder("D:/claude_work/model/bge-base-zh-v1.5")
            except Exception as e:
                logger.warning("BGE embedder init failed: %s", e)

        # Build DomainContext for each discovered domain
        for domain in discovered:
            prefix = "" if domain == "ecommerce" else f"{domain}_"

            # 1. Load semantic registry
            registry = SemanticRegistry()
            metrics_path = config_dir / f"{prefix}metrics.yaml"
            if metrics_path.exists():
                registry.load(str(metrics_path))
            else:
                logger.warning("Metrics config not found for domain '%s': %s", domain, metrics_path)
                continue

            rd = {
                "metrics": registry.metrics,
                "dimensions": registry.dimensions,
                "data_sources": registry.data_sources,
            }

            # 2. Load permissions
            perm = {}
            sc = {}
            mr = {}
            perm_path = config_dir / f"{prefix}permissions.yaml"
            if not perm_path.exists() and domain != "ecommerce":
                perm_path = config_dir / "permissions.yaml"
            if perm_path.exists():
                pd = yaml.safe_load(perm_path.read_text(encoding="utf-8"))
                perm = pd.get("users", {})
                sc = pd.get("sensitive_columns", {})
                for f, t in pd.get("masking_rules", {}).items():
                    mr[f] = lambda x, tmpl=t: tmpl.format(x=x) if isinstance(x, (int, float, str)) else str(x)

            # 3. Database
            db_url = _get_db_url(domain)
            db = create_engine(db_url, echo=False)

            # 4. Core components
            validator = DSLValidator(rd)
            resolver = SemanticResolver(rd)
            scanner = SQLScanner()
            sandbox = QuerySandbox(db)
            executor = SQLExecutor(db)
            row_security = RowLevelSecurity(perm)
            col_security = ColumnLevelSecurity(sc, mr)
            clarification_detector = ClarificationDetector()

            # 5. SQLBuilder
            tm = {k: v.get("table", k) for k, v in registry.data_sources.items()}
            sql_builder = SQLBuilder(db, tm)

            # 6. RAG
            rag_retriever = None
            if embedder is not None:
                try:
                    milvus_uri = _get_milvus_uri(domain)
                    store = MilvusLiteStore(uri=milvus_uri)
                    state_file = Path(__file__).parent.parent / f".{domain}_rag_sync_state.json"
                    try:
                        auto_sync(
                            store=store,
                            embedder=embedder,
                            configs_dir=config_dir,
                            state_file=state_file,
                            yaml_prefix=prefix,
                        )
                    except Exception as sync_err:
                        logger.warning("RAG auto-sync failed for domain '%s': %s", domain, sync_err)
                    rag_retriever = RAGRetriever(store=store, embedder=embedder)
                except Exception as e:
                    logger.warning("RAG init failed for domain '%s': %s", domain, e)

            # 7. Build graph
            graph = build_graph(
                llm_client=llm,
                rag_retriever=rag_retriever,
                validator=validator,
                row_security=row_security,
                col_security=col_security,
                resolver=resolver,
                sql_builder=sql_builder,
                scanner=scanner,
                sandbox=sandbox,
                executor=executor,
                clarification_detector=clarification_detector,
                registry_dict=rd,
                llm_system_prompt=DSL_SYSTEM_PROMPT,
                checkpointer=self._checkpointer,
            )

            # 8. Assemble DomainContext
            ctx = DomainContext(
                domain=domain,
                registry_dict=rd,
                validator=validator,
                resolver=resolver,
                sql_builder=sql_builder,
                sandbox=sandbox,
                executor=executor,
                row_security=row_security,
                col_security=col_security,
                rag_retriever=rag_retriever,
                graph=graph,
            )
            self._domains[domain] = ctx
            logger.info("Domain '%s' initialized: %d metrics, %d dimensions, %d data_sources",
                        domain, len(rd["metrics"]), len(rd["dimensions"]), len(rd["data_sources"]))
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/unit/test_domain_discovery.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nl2dsl/engine.py tests/unit/test_domain_discovery.py
git commit -m "feat(engine): multi-domain support with auto-discovery"
```

---

### Task 4: 修改 graph/state.py — 加 domain 字段

**Files:**
- Modify: `nl2dsl/graph/state.py`

- [ ] **Step 1: 在 QueryState 中加 domain 字段**

```python
class QueryState(TypedDict):
    # Input fields (set once at start)
    question: str
    domain: str               # 新增：请求的领域
    user_id: str
    tenant_id: str
    data_source: str | None
    # ... rest unchanged
```

- [ ] **Step 2: Commit**

```bash
git add nl2dsl/graph/state.py
git commit -m "feat(graph): add domain field to QueryState"
```

---

### Task 5: 修改 api.py — 路由改造 + 剥离 mock 数据

**Files:**
- Modify: `nl2dsl/api.py`
- Modify: `scripts/generate_bank_data.py`
- Create: `scripts/seed_ecommerce_data.py`

- [ ] **Step 1: 创建 seed_ecommerce_data.py**

从 `api.py` 中提取 mock 数据插入逻辑，放到独立脚本：

```python
"""Seed ecommerce mock data into the database.

Run once: python scripts/seed_ecommerce_data.py
"""

from __future__ import annotations

import random

from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Float, DateTime, insert, text

random.seed(42)


def seed_ecommerce_data(db_url: str = "sqlite:///./nl2dsl.db") -> None:
    engine = create_engine(db_url)
    metadata = MetaData()

    order_fact = Table(
        "order_fact", metadata,
        Column("id", Integer, primary_key=True),
        Column("product_id", Integer),
        Column("product_name", String),
        Column("brand", String),
        Column("category", String),
        Column("region", String),
        Column("region_code", String),
        Column("channel", String),
        Column("customer_id", Integer),
        Column("customer_type", String),
        Column("order_amount", Float),
        Column("discount_amount", Float),
        Column("pay_amount", Float),
        Column("quantity", Integer),
        Column("order_date", String),
        Column("tenant_id", String),
    )

    product_dim = Table(
        "product_dim", metadata,
        Column("product_id", Integer, primary_key=True),
        Column("product_name", String),
        Column("brand", String),
        Column("category", String),
        Column("price", Float),
    )

    customer_dim = Table(
        "customer_dim", metadata,
        Column("customer_id", Integer, primary_key=True),
        Column("customer_name", String),
        Column("customer_type", String),
        Column("register_date", String),
        Column("region", String),
    )

    metadata.create_all(engine)

    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM order_fact"))
        if result.scalar() > 0:
            print("Ecommerce data already exists, skipping.")
            return

        # Insert products
        products = [
            {"product_id": 1, "product_name": "iPhone 15 Pro", "brand": "苹果", "category": "手机", "price": 7999.0},
            {"product_id": 2, "product_name": "华为 Mate 60 Pro", "brand": "华为", "category": "手机", "price": 6999.0},
            {"product_id": 3, "product_name": "小米 14", "brand": "小米", "category": "手机", "price": 3999.0},
            {"product_id": 4, "product_name": "联想拯救者 Y9000P", "brand": "联想", "category": "电脑", "price": 8999.0},
            {"product_id": 5, "product_name": "MacBook Pro 14", "brand": "苹果", "category": "电脑", "price": 14999.0},
            {"product_id": 6, "product_name": "海尔冰箱 500L", "brand": "海尔", "category": "家电", "price": 3999.0},
            {"product_id": 7, "product_name": "美的空调 1.5匹", "brand": "美的", "category": "家电", "price": 2699.0},
            {"product_id": 8, "product_name": "Nike Air Max", "brand": "Nike", "category": "服饰", "price": 899.0},
            {"product_id": 9, "product_name": "索尼电视 65寸", "brand": "索尼", "category": "家电", "price": 5999.0},
            {"product_id": 10, "product_name": "优衣库羽绒服", "brand": "优衣库", "category": "服饰", "price": 499.0},
        ]
        conn.execute(insert(product_dim), products)

        # Insert customers
        customers = [
            {"customer_id": 1, "customer_name": "张三", "customer_type": "VIP", "register_date": "2023-01-15", "region": "华东"},
            {"customer_id": 2, "customer_name": "李四", "customer_type": "老客", "register_date": "2023-03-20", "region": "华东"},
            {"customer_id": 3, "customer_name": "王五", "customer_type": "新客", "register_date": "2024-01-05", "region": "华南"},
            {"customer_id": 4, "customer_name": "赵六", "customer_type": "VIP", "register_date": "2022-08-10", "region": "华北"},
            {"customer_id": 5, "customer_name": "孙七", "customer_type": "老客", "register_date": "2023-06-18", "region": "西南"},
        ]
        conn.execute(insert(customer_dim), customers)

        # Insert orders
        regions = ["华东", "华南", "华北", "西南"]
        order_records = []
        for i in range(50):
            pid = random.randint(1, 10)
            cid = random.randint(1, 5)
            region = regions[i % 4]
            qty = random.randint(1, 5)
            price = products[pid - 1]["price"]
            amount = round(price * qty, 2)
            discount = round(amount * random.choice([0, 0.05, 0.10, 0.15]), 2)
            order_records.append({
                "id": i + 1,
                "product_id": pid,
                "product_name": products[pid - 1]["product_name"],
                "brand": products[pid - 1]["brand"],
                "category": products[pid - 1]["category"],
                "region": region,
                "region_code": region[:2],
                "channel": random.choice(["线上", "线下", "分销"]),
                "customer_id": cid,
                "customer_type": random.choice(["VIP", "老客", "新客"]),
                "order_amount": amount,
                "discount_amount": discount,
                "pay_amount": round(amount - discount, 2),
                "quantity": qty,
                "order_date": f"2024-01-{random.randint(1, 31):02d}",
                "tenant_id": "t001" if random.random() < 0.6 else "t002",
            })
        conn.execute(insert(order_fact), order_records)
        conn.commit()
        print("Ecommerce mock data seeded successfully.")


if __name__ == "__main__":
    seed_ecommerce_data()
```

- [ ] **Step 2: 从 api.py 删除 mock 数据插入逻辑**

删除 `api.py` 中从 `# Insert mock data if tables are empty` 到 `conn.commit()` 的所有代码，以及相关的 `random` import。

- [ ] **Step 3: 修改 api.py 的路由**

修改 `QueryRequest`：

```python
class QueryRequest(BaseModel):
    question: str = Field(..., description="用户自然语言问题")
    domain: str = Field(default="ecommerce", description="业务领域")
    user_id: str = Field(..., description="用户ID")
    tenant_id: str = Field(..., description="租户ID")
```

修改 `query` 路由：

```python
@app.post("/api/v1/query")
async def query(req: QueryRequest):
    ctx = _nl2dsl_engine.get_domain(req.domain)
    if ctx is None:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "error": f"Unknown domain: {req.domain}. Available: {_nl2dsl_engine.domains}",
            },
        )

    state = QueryState(
        question=req.question,
        domain=req.domain,
        user_id=req.user_id,
        tenant_id=req.tenant_id,
        data_source=None,
        original_question=None,
        rewrite_reason=None,
        verify_status=None,
        verify_reason=None,
        ambiguities=None,
        dsl=None,
        dsl_attempts=None,
        sql=None,
        sandbox_result=None,
        complexity=None,
        data=None,
        status="pending",
        error=None,
        error_code=None,
        trace=None,
        query_id=str(uuid.uuid4()),
        started_at=time.time(),
        llm_used=bool(settings.llm_api_key),
    )

    try:
        result = await ctx.graph.ainvoke(state)
        return {"status": "success", "data": result.get("data")}
    except Exception as e:
        logger.exception("Query failed")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": str(e)},
        )
```

修改 schema/metrics 路由：

```python
@app.get("/api/v1/schema")
async def get_schema(domain: str = Query(default="ecommerce")):
    ctx = _nl2dsl_engine.get_domain(domain)
    if ctx is None:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "error": f"Unknown domain: {domain}"},
        )
    return {
        "status": "success",
        "data": {
            "metrics": ctx.registry_dict["metrics"],
            "dimensions": ctx.registry_dict["dimensions"],
            "data_sources": ctx.registry_dict["data_sources"],
        },
    }


@app.get("/api/v1/metrics")
async def get_metrics(domain: str = Query(default="ecommerce")):
    ctx = _nl2dsl_engine.get_domain(domain)
    if ctx is None:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "error": f"Unknown domain: {domain}"},
        )
    return {"status": "success", "data": list(ctx.registry_dict["metrics"].keys())}
```

- [ ] **Step 4: 清理 api.py 中不再需要的导入和全局变量**

删除以下不再需要的代码：
- `_registry = SemanticRegistry()` 及后续加载逻辑（已从 engine 加载）
- `_registry_dict` 全局变量
- `_permissions` / `_sensitive_columns` / `_masking_rules` 加载逻辑（已从 engine 加载）
- `_metadata` / `Table` 定义（mock 数据已剥离）
- 相关的 `yaml`, `MetaData`, `Table`, `Column`, `Integer`, `String`, `Float`, `DateTime`, `insert`, `text` 等导入（只保留需要的）

- [ ] **Step 5: Commit**

```bash
git add nl2dsl/api.py scripts/seed_ecommerce_data.py
git commit -m "feat(api): multi-domain routing, extract mock data to seed script"
```

---

### Task 6: 修改 rag/sync.py — auto_sync 支持 per-domain

**Files:**
- Modify: `nl2dsl/rag/sync.py`

- [ ] **Step 1: 确认 auto_sync 已支持 yaml_prefix**

在 Task 3 的 engine.py 中已经调用了 `auto_sync(..., yaml_prefix=prefix)`。检查 `sync.py` 中的 `auto_sync` 函数是否已接受 `yaml_prefix` 参数。

如果还没改，修改 `auto_sync` 签名：

```python
def auto_sync(
    store: VectorStore,
    embedder=None,
    configs_dir: str | Path = "configs",
    state_file: str | Path = ".rag_sync_state.json",
    force: bool = False,
    yaml_prefix: str = "",
) -> dict[str, int]:
```

并在函数体中使用 `yaml_prefix` 构造 YAML 路径：

```python
for yaml_name, collections in _CONFIG_COLLECTIONS.items():
    yaml_path = configs_dir / f"{yaml_prefix}{yaml_name}"
```

- [ ] **Step 2: Commit**

```bash
git add nl2dsl/rag/sync.py
git commit -m "feat(rag): auto_sync supports per-domain YAML prefix"
```

---

### Task 7: 修改 generate_bank_data.py

**Files:**
- Modify: `scripts/generate_bank_data.py`

- [ ] **Step 1: 修改默认 db_path**

```python
def create_bank_database(db_path: str = "bank.db", num_customers: int = 100, num_txns: int = 2000) -> str:
    # ... rest unchanged
```

- [ ] **Step 2: Commit**

```bash
git add scripts/generate_bank_data.py
git commit -m "refactor(bank): default output to bank.db"
```

---

### Task 8: 修改 .env.example

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: 删掉 NL2DSL_DOMAIN**

```bash
# LLM 配置（智谱AI - BigModel）
NL2DSL_LLM_API_KEY=your-api-key-here
NL2DSL_LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
NL2DSL_LLM_MODEL=glm-4.5-air

# 数据库配置（ecommerce 默认数据库）
# 其他领域的数据库自动命名为 {domain}.db
NL2DSL_DB_URL=sqlite:///./nl2dsl.db

# 向量存储配置（ecommerce 默认向量库）
# 其他领域的向量库自动命名为 {domain}_milvus_lite.db
NL2DSL_MILVUS_URI=./milvus_lite.db

# 查询限制
NL2DSL_MAX_LIMIT=10000
NL2DSL_QUERY_TIMEOUT=30
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "docs(env): remove NL2DSL_DOMAIN, document auto-naming"
```

---

### Task 9: 集成测试

**Files:**
- Create: `tests/integration/test_multi_domain.py`

- [ ] **Step 1: 写集成测试**

```python
"""Integration tests for multi-domain support."""

import pytest

from nl2dsl.engine import Engine


@pytest.fixture(scope="module")
def engine():
    return Engine()


def test_both_domains_loaded(engine):
    """Both ecommerce and bank domains are discovered."""
    assert "ecommerce" in engine.domains
    assert "bank" in engine.domains


def test_ecommerce_has_order_metrics(engine):
    ctx = engine.get_domain("ecommerce")
    assert "sales_amount" in ctx.registry_dict["metrics"]
    assert "order_count" in ctx.registry_dict["metrics"]


def test_bank_has_balance_metrics(engine):
    ctx = engine.get_domain("bank")
    assert "total_balance" in ctx.registry_dict["metrics"]
    assert "available_balance" in ctx.registry_dict["metrics"]


def test_ecommerce_db_is_separate(engine):
    """Ecommerce and bank use different databases."""
    ecommerce_ctx = engine.get_domain("ecommerce")
    bank_ctx = engine.get_domain("bank")

    # Verify by checking they have different table structures
    from sqlalchemy import inspect
    ecommerce_tables = set(inspect(ecommerce_ctx.sql_builder._engine).get_table_names())
    bank_tables = set(inspect(bank_ctx.sql_builder._engine).get_table_names())

    assert "order_fact" in ecommerce_tables
    assert "t_cif_base" in bank_tables


def test_unknown_domain_fallback(engine):
    """Unknown domain falls back to ecommerce."""
    ctx = engine.get_domain("nonexistent")
    assert ctx.domain == "ecommerce"
```

- [ ] **Step 2: 运行集成测试**

```bash
pytest tests/integration/test_multi_domain.py -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_multi_domain.py
git commit -m "test(integration): multi-domain load and isolation"
```

---

### Task 10: 端到端验证

- [ ] **Step 1: 启动服务测试 ecommerce 领域**

```bash
python scripts/seed_ecommerce_data.py
# 启动服务
uvicorn nl2dsl.api:app --reload &

# 测试 ecommerce 查询
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "查询销售额", "user_id": "u001", "tenant_id": "t001"}'
```

Expected: 返回电商订单数据

- [ ] **Step 2: 测试 bank 领域**

```bash
# 先生成 bank 数据
python scripts/generate_bank_data.py --db-path bank.db

# 测试 bank 查询
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"domain": "bank", "question": "查询总余额", "user_id": "u001", "tenant_id": "t001"}'
```

Expected: 返回银行账户余额数据

- [ ] **Step 3: 测试 Schema 路由**

```bash
# ecommerce schema
curl "http://localhost:8000/api/v1/schema"

# bank schema
curl "http://localhost:8000/api/v1/schema?domain=bank"
```

Expected: 分别返回对应领域的指标和维度定义

- [ ] **Step 4: Commit (如果有修正)**

---

## Self-Review Checklist

1. **Spec coverage:**
   - DomainContext dataclass -> Task 1
   - 自动发现 -> Task 3 (engine.py)
   - 数据库自动命名 -> Task 3 (_get_db_url / _get_milvus_uri)
   - API 改造 -> Task 5
   - Graph State domain 字段 -> Task 4
   - RAG per-domain -> Task 3/6
   - 向后兼容 -> Task 5 (default="ecommerce")
   - Mock 数据剥离 -> Task 5
   - 测试 -> Task 3/9/10

2. **Placeholder scan:** 无 TBD/TODO/"implement later"

3. **Type consistency:**
   - `DomainContext` 在 Task 1 中定义，Task 3 中实例化，Task 9 中访问 —— 一致
   - `Engine.domains` 返回 `list[str]`，`get_domain` 返回 `DomainContext` —— 一致
   - `QueryState.domain: str` —— 一致
