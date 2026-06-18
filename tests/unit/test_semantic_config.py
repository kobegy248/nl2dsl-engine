"""Tests for SemanticConfig populated from real configs/metrics.yaml.

Covers Week 2 Task 1: dimension type + value_map enrichment so that
F001/F002/F005 actually fire in production.
"""

from pathlib import Path

from nl2dsl.semantic.registry import SemanticRegistry
from nl2dsl.optimizer.context import SemanticConfig

CONFIGS_DIR = Path(__file__).resolve().parents[2] / "configs"


def _load_ecommerce_config() -> SemanticConfig:
    registry = SemanticRegistry()
    registry.load(str(CONFIGS_DIR / "metrics.yaml"))
    return SemanticConfig.from_registry_dict(
        {
            "metrics": registry.metrics,
            "dimensions": registry.dimensions,
            "data_sources": registry.data_sources,
        }
    )


def _load_bank_config() -> SemanticConfig:
    registry = SemanticRegistry()
    registry.load(str(CONFIGS_DIR / "bank_metrics.yaml"))
    return SemanticConfig.from_registry_dict(
        {
            "metrics": registry.metrics,
            "dimensions": registry.dimensions,
            "data_sources": registry.data_sources,
        }
    )


class TestEcommerceDimensionTypes:
    def test_price_is_float(self):
        config = _load_ecommerce_config()
        assert config.get_dimension_type("price") == "float"

    def test_string_dimensions_default(self):
        config = _load_ecommerce_config()
        assert config.get_dimension_type("product_name") == "string"
        assert config.get_dimension_type("brand") == "string"

    def test_order_date_is_date(self):
        config = _load_ecommerce_config()
        assert config.get_dimension_type("order_date") == "date"


class TestEcommerceValueMaps:
    def test_region_value_map_exists(self):
        config = _load_ecommerce_config()
        vm = config.get_value_map("region")
        assert vm is not None
        assert vm["华东"] == "HD"

    def test_channel_value_map(self):
        config = _load_ecommerce_config()
        vm = config.get_value_map("channel")
        assert vm is not None
        assert vm["线上"] == "online"
        assert vm["线下"] == "offline"

    def test_category_value_map(self):
        config = _load_ecommerce_config()
        vm = config.get_value_map("category")
        assert vm is not None
        assert vm["手机"] == "phone"

    def test_customer_type_value_map(self):
        config = _load_ecommerce_config()
        vm = config.get_value_map("customer_type")
        assert vm is not None
        assert vm["VIP"] == "vip"

    def test_no_value_map_returns_none(self):
        config = _load_ecommerce_config()
        assert config.get_value_map("price") is None


class TestBankDimensionTypes:
    def test_min_purchase_is_float(self):
        config = _load_bank_config()
        assert config.get_dimension_type("min_purchase") == "float"

    def test_org_level_is_integer(self):
        config = _load_bank_config()
        assert config.get_dimension_type("org_level") == "integer"

    def test_txn_date_is_date(self):
        config = _load_bank_config()
        assert config.get_dimension_type("txn_date") == "date"
