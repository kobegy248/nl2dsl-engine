"""E2E test fixtures for NL2DSL.

Provides mock database, mock vector store, and configured API client.
"""

from __future__ import annotations

import os
import tempfile

import pytest
import yaml
from fastapi.testclient import TestClient

from nl2dsl.api_factory import create_app
from nl2dsl.rag.embedder import MockEmbedder
from nl2dsl.rag.store import MilvusLiteStore

from tests.e2e.mock_data import create_mock_database, create_mock_bank_database


@pytest.fixture(scope="session")
def mock_engine():
    """Create a SQLite engine with 50 mock orders + 10 products + 5 customers + suppliers + regions + dates + warehouses + inventory."""
    engine, *_ = create_mock_database("sqlite:///:memory:")
    yield engine
    engine.dispose()


@pytest.fixture
def mock_registry_dict():
    """Load test-specific semantic registry."""
    fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    metrics_path = os.path.join(fixtures_dir, "metrics_test.yaml")
    with open(metrics_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return {
        "metrics": data.get("metrics", {}),
        "dimensions": data.get("dimensions", {}),
        "data_sources": data.get("data_sources", {}),
    }


@pytest.fixture
def mock_permissions():
    """Load test-specific permissions."""
    fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    perm_path = os.path.join(fixtures_dir, "permissions_test.yaml")
    with open(perm_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("users", {}), data.get("sensitive_columns", {}), data.get("masking_rules", {})


@pytest.fixture
def mock_vector_store():
    """Create a temporary Milvus Lite store with test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        uri = os.path.join(tmpdir, "test_milvus.db")
        store = MilvusLiteStore(uri=uri)
        embedder = MockEmbedder()

        # Create collections
        store.create_collection("schema", dimension=384)
        store.create_collection("metrics", dimension=384)
        store.create_collection("terms", dimension=384)
        store.create_collection("history", dimension=384)

        fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")

        # Insert schema records
        schema_records = [
            {
                "id": "table_order_fact",
                "vector": embedder.embed("表: order_fact, 订单事实表, 包含订单金额、优惠金额、实付金额等"),
                "text": "表: order_fact, 说明: 订单事实表, 字段: id, order_no, product_id, product_name, category, region, region_code, channel, channel_code, customer_id, order_amount, discount_amount, pay_amount, quantity, order_date, date_id, tenant_id",
                "type": "table",
                "name": "order_fact",
            },
            {
                "id": "table_product_dim",
                "vector": embedder.embed("表: product_dim, 产品维度表, 包含产品名称、品牌、品类、单价"),
                "text": "表: product_dim, 说明: 产品维度表, 字段: product_id, product_name, brand, category, price",
                "type": "table",
                "name": "product_dim",
            },
            {
                "id": "table_customer_dim",
                "vector": embedder.embed("表: customer_dim, 客户维度表, 包含客户名称、客户类型、注册日期、地区"),
                "text": "表: customer_dim, 说明: 客户维度表, 字段: customer_id, customer_name, customer_type, register_date, region",
                "type": "table",
                "name": "customer_dim",
            },
            {
                "id": "table_supplier_dim",
                "vector": embedder.embed("表: supplier_dim, 供应商维度表, 包含供应商名称、类型、地区、信用等级、合作年限"),
                "text": "表: supplier_dim, 说明: 供应商维度表, 字段: supplier_id, supplier_name, supplier_type, region, contact_name, credit_rating, cooperation_years",
                "type": "table",
                "name": "supplier_dim",
            },
            {
                "id": "table_region_dim",
                "vector": embedder.embed("表: region_dim, 区域维度表, 包含区域编码、名称、省份、城市、城市等级、人口"),
                "text": "表: region_dim, 说明: 区域维度表, 字段: region_code, region_name, province, city, tier_level, population_millions",
                "type": "table",
                "name": "region_dim",
            },
            {
                "id": "table_date_dim",
                "vector": embedder.embed("表: date_dim, 日期维度表, 包含日期ID、年月日、季度、星期、是否周末、是否节假日"),
                "text": "表: date_dim, 说明: 日期维度表, 字段: date_id, full_date, year, month, quarter, day_of_week, is_weekend, is_holiday, fiscal_year",
                "type": "table",
                "name": "date_dim",
            },
            {
                "id": "table_warehouse_dim",
                "vector": embedder.embed("表: warehouse_dim, 仓库维度表, 包含仓库名称、类型、所属区域、容量、状态"),
                "text": "表: warehouse_dim, 说明: 仓库维度表, 字段: warehouse_id, warehouse_name, warehouse_type, region, region_code, capacity, status",
                "type": "table",
                "name": "warehouse_dim",
            },
            {
                "id": "table_inventory_fact",
                "vector": embedder.embed("表: inventory_fact, 库存事实表, 包含产品在各仓库的库存数量、可用数量、预留数量、日均销量、可售天数"),
                "text": "表: inventory_fact, 说明: 库存事实表, 字段: id, product_id, product_name, brand, category, warehouse_id, warehouse_name, region, region_code, date_id, date_str, stock_quantity, available_quantity, reserved_quantity, avg_daily_sales, days_of_supply",
                "type": "table",
                "name": "inventory_fact",
            },
        ]
        store.upsert("schema", schema_records)

        # Insert metric records
        metrics_path = os.path.join(fixtures_dir, "metrics_test.yaml")
        with open(metrics_path, "r", encoding="utf-8") as f:
            metrics_data = yaml.safe_load(f)

        metric_records = []
        for name, info in metrics_data.get("metrics", {}).items():
            text = f"指标: {name}, 计算方式: {info.get('expr', '')}, 说明: {info.get('description', '')}"
            metric_records.append({
                "id": f"metric_{name}",
                "vector": embedder.embed(text),
                "text": text,
                "type": "metric",
                "name": name,
            })
        store.upsert("metrics", metric_records)

        # Insert term records
        terms_path = os.path.join(fixtures_dir, "terms_test.yaml")
        with open(terms_path, "r", encoding="utf-8") as f:
            terms_data = yaml.safe_load(f)

        term_records = []
        for name, info in terms_data.get("terms", {}).items():
            aliases = ", ".join(info.get("aliases", []))
            text = f"术语: {name}({aliases}), 说明: {info.get('description', '')}"
            term_records.append({
                "id": f"term_{name}",
                "vector": embedder.embed(text),
                "text": text,
                "type": "term",
                "name": name,
            })
        store.upsert("terms", term_records)

        # Insert history records (few-shot examples)
        history_records = [
            {
                "id": "hist_001",
                "vector": embedder.embed("查询华东地区销售额最高的产品"),
                "text": "问题: 查询华东地区销售额最高的产品, DSL: {\"metrics\": [{\"func\": \"sum\", \"field\": \"pay_amount\", \"alias\": \"sales_amount\"}], \"dimensions\": [\"product_name\"], \"filters\": [{\"field\": \"region\", \"operator\": \"=\", \"value\": \"华东\"}], \"order_by\": [{\"field\": \"sales_amount\", \"direction\": \"desc\"}], \"limit\": 10, \"data_source\": \"orders\"}",
                "type": "history",
            },
            {
                "id": "hist_002",
                "vector": embedder.embed("各品类的订单量对比"),
                "text": "问题: 各品类的订单量对比, DSL: {\"metrics\": [{\"func\": \"count\", \"field\": \"id\", \"alias\": \"order_count\"}], \"dimensions\": [\"category\"], \"data_source\": \"orders\"}",
                "type": "history",
            },
            {
                "id": "hist_003",
                "vector": embedder.embed("线上渠道的客单价排名"),
                "text": "问题: 线上渠道的客单价排名, DSL: {\"metrics\": [{\"func\": \"avg\", \"field\": \"pay_amount\", \"alias\": \"avg_order_value\"}], \"dimensions\": [\"channel\"], \"filters\": [{\"field\": \"channel\", \"operator\": \"=\", \"value\": \"线上\"}], \"order_by\": [{\"field\": \"avg_order_value\", \"direction\": \"desc\"}], \"data_source\": \"orders\"}",
                "type": "history",
            },
        ]
        store.upsert("history", history_records)

        yield store


@pytest.fixture
def mock_api_client(mock_engine, mock_registry_dict, mock_permissions):
    """Create a TestClient with mock data injected."""
    permissions, sensitive_columns, masking_rules = mock_permissions
    app = create_app(
        engine=mock_engine,
        registry_dict=mock_registry_dict,
        permissions=permissions,
        sensitive_columns=sensitive_columns,
        masking_rules=masking_rules,
    )
    return TestClient(app)


# ---------------------------------------------------------------------------
# Bank domain fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def bank_engine():
    """Create a SQLite engine with bank mock data."""
    engine, *_ = create_mock_bank_database("sqlite:///:memory:")
    yield engine
    engine.dispose()


@pytest.fixture
def bank_registry_dict():
    """Load test-specific bank semantic registry."""
    fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    metrics_path = os.path.join(fixtures_dir, "bank_metrics_test.yaml")
    with open(metrics_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return {
        "metrics": data.get("metrics", {}),
        "dimensions": data.get("dimensions", {}),
        "data_sources": data.get("data_sources", {}),
    }


@pytest.fixture
def bank_permissions():
    """Load test-specific bank permissions."""
    fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    perm_path = os.path.join(fixtures_dir, "bank_permissions_test.yaml")
    with open(perm_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("users", {}), data.get("sensitive_columns", {}), data.get("masking_rules", {})


@pytest.fixture
def bank_api_client(bank_engine, bank_registry_dict, bank_permissions):
    """Create a TestClient with bank domain configuration."""
    permissions, sensitive_columns, masking_rules = bank_permissions
    app = create_app(
        engine=bank_engine,
        registry_dict=bank_registry_dict,
        permissions=permissions,
        sensitive_columns=sensitive_columns,
        masking_rules=masking_rules,
    )
    return TestClient(app)
