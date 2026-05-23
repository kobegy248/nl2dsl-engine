import pytest
from nl2dsl.plugin import Plugin
from nl2dsl.engine import Engine


class TestPluginABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            Plugin()

    def test_subclass_must_implement_register(self):
        class BadPlugin(Plugin):
            pass

        with pytest.raises(TypeError):
            BadPlugin()

    def test_name_defaults_to_class_name(self):
        class MyPlugin(Plugin):
            def register(self, engine):
                pass

        assert MyPlugin().name == "MyPlugin"

    def test_priority_defaults_to_100(self):
        class MyPlugin(Plugin):
            def register(self, engine):
                pass

        assert MyPlugin().priority == 100

    def test_custom_priority(self):
        class HighPriorityPlugin(Plugin):
            @property
            def priority(self):
                return 10

            def register(self, engine):
                pass

        assert HighPriorityPlugin().priority == 10

    def test_subclass_can_override_name(self):
        class NamedPlugin(Plugin):
            @property
            def name(self):
                return "custom-name"

            def register(self, engine):
                pass

        assert NamedPlugin().name == "custom-name"

    def test_register_receives_engine(self):
        received = []

        class CapturePlugin(Plugin):
            def register(self, engine):
                received.append(engine)

        engine = Engine()
        plugin = CapturePlugin()
        engine.use(plugin).build()
        assert len(received) == 1
        assert received[0] is engine
