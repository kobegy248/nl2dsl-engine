"""NL2DSL Engine entry point."""
from __future__ import annotations
from pathlib import Path

import yaml
from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine

from nl2dsl.config import settings
from nl2dsl.plugin import Registry, Pipeline, Plugin
from nl2dsl.graph.builder import build_graph
from nl2dsl.utils.logger import get_logger

logger = get_logger("engine")


class Engine:
    def __init__(self):
        self._registry = Registry()
        self._pipeline = Pipeline()
        self._plugins: list[Plugin] = []
        self._built = False
        self._checkpointer = InMemorySaver()
        self._load_defaults()

    def use(self, plugin: Plugin) -> "Engine":
        self._plugins.append(plugin)
        return self

    def register(self, name: str, component) -> "Engine":
        self._registry.register(name, component)
        return self

    @property
    def registry(self) -> Registry:
        return self._registry

    @property
    def pipeline(self) -> Pipeline:
        return self._pipeline

    def build(self):
        if self._built:
            raise RuntimeError("Engine.build() can only be called once")
        for plugin in sorted(self._plugins, key=lambda p: p.priority):
            logger.info("Loading plugin: %s (priority=%d)", plugin.name, plugin.priority)
            plugin.register(self)
        graph = build_graph(
            llm_client=self._registry.get("llm") if self._registry.has("llm") else None,
            rag_retriever=self._registry.get("rag_retriever") if self._registry.has("rag_retriever") else None,
            validator=self._registry.get("validator"),
            row_security=self._registry.get("row_security"),
            col_security=self._registry.get("col_security"),
            resolver=self._registry.get("resolver"),
            sql_builder=self._registry.get("sql_builder"),
            scanner=self._registry.get("scanner"),
            sandbox=self._registry.get("sandbox"),
            executor=self._registry.get("executor"),
            clarification_detector=self._registry.get("clarification_detector"),
            registry_dict=self._registry.get("registry_dict"),
            llm_system_prompt=self._registry.get("llm_system_prompt") if self._registry.has("llm_system_prompt") else "",
            checkpointer=self._checkpointer,
        )
        self._built = True
        return graph

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

        # Semantic registry
        registry = SemanticRegistry()
        p = Path(__file__).parent.parent / "configs" / "metrics.yaml"
        if p.exists():
            registry.load(str(p))
        rd = {"metrics": registry.metrics, "dimensions": registry.dimensions, "data_sources": registry.data_sources}
        self._registry.register("registry_dict", rd)

        # Permissions
        perm = {}
        sc = {}
        mr = {}
        pp = Path(__file__).parent.parent / "configs" / "permissions.yaml"
        if pp.exists():
            pd = yaml.safe_load(pp.read_text(encoding="utf-8"))
            perm = pd.get("users", {})
            sc = pd.get("sensitive_columns", {})
            for f, t in pd.get("masking_rules", {}).items():
                mr[f] = lambda x, tmpl=t: tmpl.format(x=x) if isinstance(x, (int, float, str)) else str(x)

        # DB + core components
        db = create_engine(settings.db_url, echo=False)
        self._registry.register("db_engine", db)
        self._registry.register("validator", DSLValidator(rd))
        self._registry.register("resolver", SemanticResolver(rd))
        self._registry.register("scanner", SQLScanner())
        self._registry.register("sandbox", QuerySandbox(db))
        self._registry.register("executor", SQLExecutor(db))
        self._registry.register("row_security", RowLevelSecurity(perm))
        self._registry.register("col_security", ColumnLevelSecurity(sc, mr))
        self._registry.register("clarification_detector", ClarificationDetector())
        self._registry.register("llm_system_prompt", DSL_SYSTEM_PROMPT)
        tm = {k: v.get("table", k) for k, v in registry.data_sources.items()}
        self._registry.register("sql_builder", SQLBuilder(db, tm))

        # LLM (optional)
        if settings.llm_api_key:
            llm = LLMClient(api_key=settings.llm_api_key, base_url=settings.llm_base_url, model=settings.llm_model)
            self._registry.register("llm", llm)
            try:
                store = MilvusLiteStore(uri=settings.milvus_uri)
                emb = BGEEmbedder("D:/claude_work/model/bge-base-zh-v1.5")
                # 启动自检：对比 YAML mtime，按需同步到向量库
                from nl2dsl.rag.sync import auto_sync
                configs_dir = Path(__file__).parent.parent / "configs"
                state_file = Path(__file__).parent.parent / ".rag_sync_state.json"
                try:
                    auto_sync(store=store, embedder=emb, configs_dir=configs_dir, state_file=state_file)
                except Exception as sync_err:
                    logger.warning("RAG auto-sync failed: %s", sync_err)
                # 同步完成后再创建 retriever（确保 _load_keywords 能读到数据）
                ret = RAGRetriever(store=store, embedder=emb)
                self._registry.register("rag_retriever", ret)
            except Exception as e:
                logger.warning("RAG init failed: %s", e)
