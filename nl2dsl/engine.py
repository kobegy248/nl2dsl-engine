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
                        # TODO: yaml_prefix support will be added in Task 6
                        # For now, call auto_sync without yaml_prefix
                        auto_sync(
                            store=store,
                            embedder=embedder,
                            configs_dir=config_dir,
                            state_file=state_file,
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
