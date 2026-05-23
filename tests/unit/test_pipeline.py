import pytest
from nl2dsl.plugin import Pipeline


def _node(s): return {"r": "orig"}
def _hook(s): return {"h": True}
def _err(s): return {"status": "error"}


class TestPipeline:
    def test_before(self):
        pl = Pipeline().set_default_nodes({"n": _node}).before("n", _hook)
        r = pl.compile()["n"]({})
        assert r["r"] == "orig" and r["h"] is True

    def test_after(self):
        pl = Pipeline().set_default_nodes({"n": _node}).after("n", _hook)
        r = pl.compile()["n"]({})
        assert r["r"] == "orig" and r["h"] is True

    def test_before_interrupt(self):
        pl = Pipeline().set_default_nodes({"n": _node}).before("n", _err)
        r = pl.compile()["n"]({})
        assert r["status"] == "error" and "r" not in r

    def test_replace(self):
        pl = Pipeline().set_default_nodes({"n": _node}).replace("n", lambda s: {"r": "new"})
        assert pl.compile()["n"]({}) == {"r": "new"}

    def test_add_node(self):
        pl = Pipeline().set_default_nodes({"a": _node, "b": _node}).add_node("c", lambda s: {"r": "c"}, after="a")
        assert "c" in pl.compile()

    def test_add_unknown_after_raises(self):
        with pytest.raises(ValueError):
            Pipeline().set_default_nodes({"a": _node}).add_node("c", _node, "x").compile()

    def test_after_interrupt(self):
        pl = Pipeline().set_default_nodes({"n": _node}).after("n", _err)
        r = pl.compile()["n"]({})
        assert r["status"] == "error" and "r" not in r

    def test_replace_unknown_raises(self):
        with pytest.raises(ValueError):
            Pipeline().set_default_nodes({"a": _node}).replace("x", _node).compile()

    def test_node_names(self):
        pl = Pipeline().set_default_nodes({"a": _node, "b": _node}).add_node("c", _node, after="a")
        assert pl.node_names() == ["a", "b", "c"]

    def test_multiple_before_hooks_order(self):
        calls = []

        def hook1(s):
            calls.append(1)
            return {}

        def hook2(s):
            calls.append(2)
            return {}

        pl = Pipeline().set_default_nodes({"n": _node}).before("n", hook1).before("n", hook2)
        pl.compile()["n"]({})
        assert calls == [1, 2]

    def test_multiple_after_hooks_order(self):
        calls = []

        def hook1(s):
            calls.append(1)
            return {}

        def hook2(s):
            calls.append(2)
            return {}

        pl = Pipeline().set_default_nodes({"n": _node}).after("n", hook1).after("n", hook2)
        pl.compile()["n"]({})
        assert calls == [1, 2]

    def test_empty_pipeline(self):
        pl = Pipeline()
        assert pl.compile() == {}
        assert pl.node_names() == []

    def test_before_hook_state_mutation(self):
        def mutator(s):
            return {"injected": True}

        def reader(s):
            return {"has_injected": s.get("injected", False)}

        pl = Pipeline().set_default_nodes({"n": reader}).before("n", mutator)
        r = pl.compile()["n"]({})
        assert r["has_injected"] is True

    def test_after_hook_sees_original_state(self):
        def node_fn(s):
            return {"node_out": 1}

        def after_fn(s):
            return {"saw_state": s.get("node_out", None)}

        pl = Pipeline().set_default_nodes({"n": node_fn}).after("n", after_fn)
        r = pl.compile()["n"]({})
        assert r["saw_state"] == 1
