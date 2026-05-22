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
