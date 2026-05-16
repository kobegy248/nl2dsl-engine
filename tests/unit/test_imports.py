"""Verify core dependencies are installable and importable."""


def test_fastapi_imports():
    import fastapi
    assert hasattr(fastapi, "FastAPI")


def test_pydantic_imports():
    import pydantic
    assert hasattr(pydantic, "BaseModel")


def test_sqlalchemy_imports():
    import sqlalchemy
    assert hasattr(sqlalchemy, "create_engine")


def test_sqlglot_imports():
    import sqlglot
    assert hasattr(sqlglot, "transpile")


def test_pymilvus_imports():
    import pymilvus
    assert hasattr(pymilvus, "MilvusClient")


def test_yaml_imports():
    import yaml
    assert hasattr(yaml, "safe_load")
