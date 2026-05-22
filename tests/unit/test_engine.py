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
