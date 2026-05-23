import pytest
from nl2dsl.engine import Engine
from nl2dsl.plugin import Plugin


class DummyPlugin(Plugin):
    def register(self, engine):
        engine.register("test_value", 42)


class TestEngine:
    def test_engine_creates_registry(self):
        engine = Engine()
        assert engine.registry.has("validator")
        assert engine.registry.has("sql_builder")
        assert engine.registry.has("executor")

    def test_engine_use_plugin(self):
        engine = Engine()
        engine.use(DummyPlugin())
        engine.build()
        assert engine.registry.get("test_value") == 42

    def test_build_once(self):
        engine = Engine()
        engine.build()
        with pytest.raises(RuntimeError):
            engine.build()

    def test_chain_api(self):
        engine = Engine()
        result = engine.register("a", 1).register("b", 2)
        assert result is engine

    def test_pipeline_property(self):
        engine = Engine()
        from nl2dsl.plugin import Pipeline
        assert isinstance(engine.pipeline, Pipeline)

    def test_plugin_priority_sorting(self):
        order = []

        class LowPriorityPlugin(Plugin):
            @property
            def priority(self):
                return 200

            def register(self, engine):
                order.append("low")

        class HighPriorityPlugin(Plugin):
            @property
            def priority(self):
                return 10

            def register(self, engine):
                order.append("high")

        engine = Engine()
        engine.use(LowPriorityPlugin()).use(HighPriorityPlugin()).build()
        assert order == ["high", "low"]

    def test_build_fastapi_app(self):
        engine = Engine()
        from fastapi import FastAPI
        app = engine.build_fastapi_app()
        assert isinstance(app, FastAPI)

    def test_default_components_loaded(self):
        engine = Engine()
        assert engine.registry.has("registry_dict")
        assert engine.registry.has("db_engine")
        assert engine.registry.has("validator")
        assert engine.registry.has("resolver")
        assert engine.registry.has("scanner")
        assert engine.registry.has("sandbox")
        assert engine.registry.has("executor")
        assert engine.registry.has("row_security")
        assert engine.registry.has("col_security")
        assert engine.registry.has("clarification_detector")
        assert engine.registry.has("llm_system_prompt")
        assert engine.registry.has("sql_builder")
