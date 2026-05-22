import pytest
from nl2dsl.plugin import Registry


class TestRegistry:
    def test_register_and_get(self):
        reg = Registry()
        reg.register("llm", {"name": "test"})
        assert reg.get("llm") == {"name": "test"}

    def test_override(self):
        reg = Registry()
        reg.register("llm", "v1")
        reg.register("llm", "v2")
        assert reg.get("llm") == "v2"

    def test_get_missing(self):
        with pytest.raises(KeyError):
            Registry().get("missing")

    def test_has(self):
        reg = Registry()
        assert not reg.has("x")
        reg.register("x", 1)
        assert reg.has("x")

    def test_names(self):
        reg = Registry()
        reg.register("a", 1).register("b", 2)
        assert reg.names() == {"a", "b"}
