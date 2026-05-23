def test_exports_engine():
    from nl2dsl import Engine
    assert Engine is not None


def test_exports_plugin():
    from nl2dsl import Plugin
    assert Plugin is not None


def test_all_specified():
    import nl2dsl
    assert nl2dsl.__all__ == ["Engine", "Plugin"]
