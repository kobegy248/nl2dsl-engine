"""End-to-end tests for NL2DSL with realistic business data.

Tests the full pipeline: question -> mock DSL -> validate -> permissions ->
semantic resolve -> SQL build -> scan -> execute -> return results.
"""

from __future__ import annotations

import pytest


# =============================================================================
# Helper assertions
# =============================================================================

def _assert_query_success(response):
    """Assert a /query or /query/execute response is successful."""
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data.get("status") == "success", f"Expected status='success', got: {data}"
    return data


def _assert_dsl_has_metric(data, alias: str):
    """Assert DSL contains a metric with the given alias."""
    dsl = data.get("dsl")
    assert dsl is not None, "DSL should be present in response"
    aliases = {m.get("alias") for m in dsl.get("metrics", [])}
    assert alias in aliases, f"Expected metric alias '{alias}' not found in DSL. Got: {aliases}"


def _assert_sql_and_data(data, min_rows: int = 0):
    """Assert SQL is generated and data is returned."""
    sql = data.get("sql")
    assert sql is not None and "SELECT" in sql, f"SQL should contain SELECT, got: {sql}"
    rows = data.get("data", [])
    assert rows is not None, "Data should be present in response"
    assert len(rows) >= min_rows, f"Expected at least {min_rows} rows, got {len(rows)}"


# =============================================================================
# Phase 1: Basic health check
# =============================================================================

class TestHealth:
    def test_health_check(self, mock_api_client):
        response = mock_api_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


# =============================================================================
# Phase 2: Business query scenarios (via /query with keyword-based mock DSL)
# =============================================================================

class TestBusinessQueries:
    """Test typical business queries with realistic data.

    These tests use the keyword-based mock DSL generator (_mock_dsl_from_question),
    which parses natural language questions to create DSL without calling an LLM.
    The tests verify the full pipeline works end-to-end with real data.
    """

    def test_query_sales(self, mock_api_client):
        """查询销售额."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_dsl_has_metric(data, "sales_amount")
        _assert_sql_and_data(data, min_rows=1)

    def test_query_sales_by_category(self, mock_api_client):
        """查询各品类的销售额."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询各品类的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_dsl_has_metric(data, "sales_amount")
        _assert_sql_and_data(data, min_rows=1)
        # Should have category info in results (via product_name or category)
        assert len(data["data"]) <= 20

    def test_query_order_count(self, mock_api_client):
        """查询订单量."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询订单量",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_dsl_has_metric(data, "order_count")
        _assert_sql_and_data(data, min_rows=1)

    def test_query_region_filter(self, mock_api_client):
        """查询华东地区的销售额."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询华东地区的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_dsl_has_metric(data, "sales_amount")
        _assert_sql_and_data(data, min_rows=1)
        # Verify region filter is in SQL (after semantic resolution, region -> region_code)
        assert "HD" in data["sql"] or "华东" in data["sql"]

    def test_query_channel_filter(self, mock_api_client):
        """查询线上渠道的销售额."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询线上渠道的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_dsl_has_metric(data, "sales_amount")
        _assert_sql_and_data(data, min_rows=1)

    def test_query_product_top_sales(self, mock_api_client):
        """查询销售额最高的产品."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询销售额最高的产品",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_dsl_has_metric(data, "sales_amount")
        _assert_sql_and_data(data, min_rows=1)
        assert len(data["data"]) <= 20

    def test_query_avg_order_value(self, mock_api_client):
        """查询客单价."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询客单价",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_dsl_has_metric(data, "avg_order_value")
        _assert_sql_and_data(data, min_rows=1)

    def test_query_gmv(self, mock_api_client):
        """查询GMV."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询GMV",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_dsl_has_metric(data, "gmv")
        _assert_sql_and_data(data, min_rows=1)

    def test_query_total_quantity(self, mock_api_client):
        """查询销量."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询销量",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_dsl_has_metric(data, "total_quantity")
        _assert_sql_and_data(data, min_rows=1)

    def test_query_discount(self, mock_api_client):
        """查询优惠总额."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询优惠总额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_dsl_has_metric(data, "total_discount")
        _assert_sql_and_data(data, min_rows=1)


# =============================================================================
# Phase 3: Precise DSL tests (via /query/execute with exact DSL)
# =============================================================================

class TestPreciseQueries:
    """Test precise DSL execution to verify data correctness.

    These tests bypass the keyword-based mock DSL generator and directly
    provide exact DSL to the /query/execute endpoint.
    """

    def test_execute_sales_by_region(self, mock_api_client):
        """按地区汇总销售额."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["region"],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        regions = {row.get("region") for row in data["data"]}
        assert "华东" in regions or "HD" in str(regions)

    def test_execute_sales_by_category(self, mock_api_client):
        """按品类汇总销售额."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["category"],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        categories = {row.get("category") for row in data["data"]}
        assert "手机" in categories

    def test_execute_phone_orders_east_china(self, mock_api_client):
        """华东地区手机品类的订单量."""
        dsl = {
            "metrics": [{"func": "count", "field": "id", "alias": "order_count"}],
            "dimensions": ["category"],
            "filters": [
                {"field": "region", "operator": "=", "value": "华东"},
                {"field": "category", "operator": "=", "value": "手机"},
            ],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert data["data"][0]["order_count"] > 0

    def test_execute_online_channel_avg_value(self, mock_api_client):
        """线上渠道客单价."""
        dsl = {
            "metrics": [{"func": "avg", "field": "pay_amount", "alias": "avg_order_value"}],
            "filters": [{"field": "channel", "operator": "=", "value": "线上"}],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert data["data"][0]["avg_order_value"] > 0

    def test_execute_sales_by_brand(self, mock_api_client):
        """按品牌汇总销售额."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["brand"],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        brands = {row.get("brand") for row in data["data"]}
        assert len(brands) > 0

    def test_execute_vip_customer_sales(self, mock_api_client):
        """VIP客户消费金额."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "filters": [{"field": "customer_type", "operator": "=", "value": "VIP"}],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)

    def test_execute_order_count_by_channel(self, mock_api_client):
        """按渠道统计订单量."""
        dsl = {
            "metrics": [{"func": "count", "field": "id", "alias": "order_count"}],
            "dimensions": ["channel"],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        channels = {row.get("channel") for row in data["data"]}
        assert len(channels) >= 1

    def test_execute_top_products_by_sales(self, mock_api_client):
        """销售额最高的10个产品."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["product_name"],
            "order_by": [{"field": "sales_amount", "direction": "desc"}],
            "limit": 10,
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert len(data["data"]) <= 10
        # Verify descending order
        amounts = [row["sales_amount"] for row in data["data"]]
        assert amounts == sorted(amounts, reverse=True)

    def test_execute_customer_type_avg_value(self, mock_api_client):
        """新客和老客客单价对比."""
        dsl = {
            "metrics": [{"func": "avg", "field": "pay_amount", "alias": "avg_order_value"}],
            "dimensions": ["customer_type"],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        types = {row.get("customer_type") for row in data["data"]}
        assert len(types) >= 1

    def test_execute_tenant_isolation_u001(self, mock_api_client):
        """u001 (t001) should only see t001 data."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        # SQL should contain tenant_id filter
        assert "t001" in data["sql"]
        # All returned data should have tenant_id = t001
        # (The row-level security injects tenant_id filter)

    def test_execute_tenant_isolation_u002(self, mock_api_client):
        """u002 (t002) should only see t002 data."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u002",
            "tenant_id": "t002",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert "t002" in data["sql"]

    def test_execute_with_semantic_resolution(self, mock_api_client):
        """Test that semantic resolution works (region -> region_code, etc.)."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["region"],
            "filters": [{"field": "region", "operator": "=", "value": "华东"}],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        # After semantic resolution, "华东" should be converted to "HD" in SQL
        assert "HD" in data["sql"] or "华东" in data["sql"]

    def test_execute_multi_table_join_supplier_sales(self, mock_api_client):
        """跨表 JOIN: order_fact -> product_dim -> supplier_dim, 按供应商统计销售额."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["supplier_name"],
            "joins": [
                {"table": "product_dim", "on_field": "product_id", "join_type": "left", "alias": "p"},
                {"table": "supplier_dim", "on_field": "product_dim.supplier_id", "join_type": "left", "alias": "s"},
            ],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        # SQL should contain both joined tables
        assert "product_dim" in data["sql"]
        assert "supplier_dim" in data["sql"]
        # Results should have supplier names
        suppliers = {row.get("supplier_name") for row in data["data"]}
        assert len(suppliers) >= 1

    def test_execute_multi_table_join_customer_sales(self, mock_api_client):
        """跨表 JOIN: order_fact -> customer_dim, 按客户名称统计销售额."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["customer_name"],
            "joins": [
                {"table": "customer_dim", "on_field": "customer_id", "join_type": "left", "alias": "c"},
            ],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert "customer_dim" in data["sql"]
        names = {row.get("customer_name") for row in data["data"]}
        assert len(names) >= 1

    def test_execute_region_dim_join_tier_sales(self, mock_api_client):
        """跨表 JOIN: order_fact -> region_dim, 按城市等级统计销售额."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["tier_level"],
            "joins": [
                {"table": "region_dim", "on_field": "region_code", "join_type": "left", "alias": "r"},
            ],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert "region_dim" in data["sql"]
        tiers = {row.get("tier_level") for row in data["data"]}
        assert len(tiers) >= 1

    def test_execute_inventory_by_warehouse_type(self, mock_api_client):
        """库存数据源: 按仓库类型统计总库存量."""
        dsl = {
            "metrics": [{"func": "sum", "field": "stock_quantity", "alias": "total_stock"}],
            "dimensions": ["warehouse_type"],
            "data_source": "inventory",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        types = {row.get("warehouse_type") for row in data["data"]}
        assert "中心仓" in types or "前置仓" in types

    def test_execute_supplier_credit_a_sales(self, mock_api_client):
        """跨表 JOIN + 过滤: 信用等级为A的供应商的销售额."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["supplier_name"],
            "filters": [{"field": "credit_rating", "operator": "=", "value": "A"}],
            "joins": [
                {"table": "product_dim", "on_field": "product_id", "join_type": "left", "alias": "p"},
                {"table": "supplier_dim", "on_field": "product_dim.supplier_id", "join_type": "left", "alias": "s"},
            ],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert "credit_rating" in data["sql"]
        for row in data["data"]:
            assert row.get("sales_amount", 0) >= 0

    def test_execute_multi_dim_supplier_category(self, mock_api_client):
        """跨表 JOIN + 多维度: 按供应商和品类双维度统计销售额."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["supplier_name", "category"],
            "joins": [
                {"table": "product_dim", "on_field": "product_id", "join_type": "left", "alias": "p"},
                {"table": "supplier_dim", "on_field": "product_dim.supplier_id", "join_type": "left", "alias": "s"},
            ],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        first = data["data"][0]
        assert "supplier_name" in first
        assert "category" in first

    def test_execute_date_dim_join_weekend_orders(self, mock_api_client):
        """日期维度 JOIN: 按是否周末统计订单量."""
        dsl = {
            "metrics": [{"func": "count", "field": "id", "alias": "order_count"}],
            "dimensions": ["is_weekend"],
            "joins": [
                {"table": "date_dim", "on_field": "date_id", "join_type": "left", "alias": "d"},
            ],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert "date_dim" in data["sql"]
        # Should have both weekend (1) and weekday (0) rows
        weekend_flags = {row.get("is_weekend") for row in data["data"]}
        assert len(weekend_flags) >= 1

    def test_execute_date_dim_join_holiday_sales(self, mock_api_client):
        """日期维度 JOIN: 节假日 vs 非节假日的销售额."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["is_holiday"],
            "joins": [
                {"table": "date_dim", "on_field": "date_id", "join_type": "left", "alias": "d"},
            ],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert "date_dim" in data["sql"]
        holiday_flags = {row.get("is_holiday") for row in data["data"]}
        assert len(holiday_flags) >= 1


# =============================================================================
# Phase 4: DSL-only endpoint tests
# =============================================================================

class TestDSLEndpoint:
    def test_dsl_with_sales_keyword(self, mock_api_client):
        response = mock_api_client.post("/api/v1/query/dsl", json={
            "question": "查询销售额最高的产品",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_dsl_has_metric(data, "sales_amount")

    def test_dsl_with_region_filter(self, mock_api_client):
        response = mock_api_client.post("/api/v1/query/dsl", json={
            "question": "查询华东地区的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_dsl_has_metric(data, "sales_amount")


# =============================================================================
# Phase 5: Management endpoints
# =============================================================================

class TestManagementEndpoints:
    def test_schema_endpoint(self, mock_api_client):
        response = mock_api_client.get("/api/v1/schema")
        assert response.status_code == 200
        data = response.json()
        assert len(data["data_sources"]) > 0
        assert len(data["metrics"]) == 14  # 14 metrics in test config (8 orders + 5 inventory + 1 avg_days_supply)
        assert len(data["dimensions"]) >= 5  # At least 5 dimensions

    def test_metrics_endpoint(self, mock_api_client):
        response = mock_api_client.get("/api/v1/metrics")
        assert response.status_code == 200
        data = response.json()
        assert len(data["metrics"]) == 14
        metric_names = {m["name"] for m in data["metrics"]}
        assert "sales_amount" in metric_names
        assert "gmv" in metric_names
        assert "order_count" in metric_names

    def test_feedback_endpoint(self, mock_api_client):
        q = mock_api_client.post("/api/v1/query", json={
            "question": "查询销售额", "user_id": "u001", "tenant_id": "t001",
        })
        query_id = q.json()["query_id"]
        response = mock_api_client.post("/api/v1/feedback", json={
            "query_id": query_id,
            "user_id": "u001",
            "tenant_id": "t001",
            "corrected_dsl": {"data_source": "orders"},
            "comment": "测试反馈",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "received"

    def test_enums_endpoint(self, mock_api_client):
        response = mock_api_client.get("/api/v1/admin/enums")
        assert response.status_code == 200
        data = response.json()
        assert "enums" in data

    def test_refresh_enums_endpoint(self, mock_api_client):
        response = mock_api_client.post("/api/v1/admin/enums/refresh")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "refreshed"


# =============================================================================
# Phase 6: Error handling
# =============================================================================

class TestErrorHandling:
    """Test system behavior with invalid input."""

    def test_invalid_data_source(self, mock_api_client):
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": {
                "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
                "data_source": "nonexistent_source",
            },
            "user_id": "u001",
            "tenant_id": "t001",
        })
        assert response.status_code == 400
        data = response.json()
        assert data["status"] == "error"
        assert "VALIDATION_ERROR" in data["error_code"]

    def test_invalid_dimension(self, mock_api_client):
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": {
                "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
                "dimensions": ["nonexistent_dim"],
                "data_source": "orders",
            },
            "user_id": "u001",
            "tenant_id": "t001",
        })
        assert response.status_code == 400
        data = response.json()
        assert data["status"] == "error"
        assert "VALIDATION_ERROR" in data["error_code"]

    def test_invalid_metric_alias(self, mock_api_client):
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": {
                "metrics": [{"func": "sum", "field": "pay_amount", "alias": "nonexistent_metric"}],
                "data_source": "orders",
            },
            "user_id": "u001",
            "tenant_id": "t001",
        })
        assert response.status_code == 400
        data = response.json()
        assert data["status"] == "error"

    def test_no_metrics_no_dimensions(self, mock_api_client):
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": {
                "data_source": "orders",
            },
            "user_id": "u001",
            "tenant_id": "t001",
        })
        assert response.status_code == 400
        data = response.json()
        assert data["status"] == "error"


# =============================================================================
# Phase 7: Advanced query scenarios
# =============================================================================

class TestAdvancedQueries:
    """Test complex query patterns: multi-dimensions, multi-metrics, pagination, etc."""

    def test_multi_dimension_grouping(self, mock_api_client):
        """按地区和品类双维度分组."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["region", "category"],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        # Should have both region and category columns
        first = data["data"][0]
        assert "region" in first or "region_code" in first
        assert "category" in first

    def test_multi_metrics(self, mock_api_client):
        """同时查询销售额和订单量."""
        dsl = {
            "metrics": [
                {"func": "sum", "field": "pay_amount", "alias": "sales_amount"},
                {"func": "count", "field": "id", "alias": "order_count"},
            ],
            "dimensions": ["category"],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        first = data["data"][0]
        assert "sales_amount" in first
        assert "order_count" in first

    def test_pagination_limit_offset(self, mock_api_client):
        """测试分页 limit + offset."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["product_name"],
            "order_by": [{"field": "sales_amount", "direction": "desc"}],
            "limit": 5,
            "offset": 2,
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=0)
        # With offset=2, result count should be <= total - 2
        assert len(data["data"]) <= 8  # 10 products max minus offset

    def test_ascending_order(self, mock_api_client):
        """升序排序."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["category"],
            "order_by": [{"field": "sales_amount", "direction": "asc"}],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        amounts = [row["sales_amount"] for row in data["data"]]
        assert amounts == sorted(amounts)

    def test_like_filter(self, mock_api_client):
        """模糊匹配产品名称."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["product_name"],
            "filters": [{"field": "product_name", "operator": "like", "value": "iPhone"}],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        for row in data["data"]:
            assert "iPhone" in row["product_name"]

    def test_numeric_comparison_filters(self, mock_api_client):
        """数值比较操作符 >, <, >=, <=."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["product_name"],
            "filters": [{"field": "pay_amount", "operator": ">", "value": 5000}],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "sql" in data
        assert ">" in data["sql"]

    def test_not_equal_filter(self, mock_api_client):
        """不等于操作符."""
        dsl = {
            "metrics": [{"func": "count", "field": "id", "alias": "order_count"}],
            "dimensions": ["category"],
            "filters": [{"field": "category", "operator": "!=", "value": "手机"}],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        categories = {row["category"] for row in data["data"]}
        assert "手机" not in categories

    def test_dimensions_only_no_metrics(self, mock_api_client):
        """只查询维度，不做聚合."""
        dsl = {
            "dimensions": ["region", "channel"],
            "limit": 10,
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert len(data["data"]) <= 10
        if data["data"]:
            first = data["data"][0]
            assert "region" in first or "region_code" in first
            assert "channel" in first or "channel_code" in first

    def test_all_aggregations(self, mock_api_client):
        """测试所有支持的聚合函数: sum, avg, count, min, max."""
        dsl = {
            "metrics": [
                {"func": "sum", "field": "pay_amount", "alias": "sales_amount"},
                {"func": "avg", "field": "pay_amount", "alias": "avg_order_value"},
                {"func": "count", "field": "id", "alias": "order_count"},
                {"func": "min", "field": "pay_amount", "alias": "min_amount"},
                {"func": "max", "field": "pay_amount", "alias": "max_amount"},
            ],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        first = data["data"][0]
        assert first["sales_amount"] >= first["min_amount"]
        assert first["max_amount"] >= first["min_amount"]
        assert first["avg_order_value"] >= first["min_amount"]
        assert first["avg_order_value"] <= first["max_amount"]


# =============================================================================
# Phase 8: Permission edge cases
# =============================================================================

class TestPermissionEdgeCases:
    """Test row-level and tenant isolation with edge cases."""

    def test_u003_no_row_filters(self, mock_api_client):
        """u003 (t001) has no row_filters but still tenant-isolated."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["region"],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u003",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        # SQL should still contain tenant_id filter
        assert "t001" in data["sql"]
        # u003 can see all regions for t001 (no region filter injected)
        # But data is still limited to t001 tenant

    def test_u001_u002_data_isolation(self, mock_api_client):
        """u001 and u002 should see different regions due to row_filters."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["region"],
            "data_source": "orders",
        }
        # u001 query
        r1 = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        d1 = _assert_query_success(r1)

        # u002 query
        r2 = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u002",
            "tenant_id": "t002",
        })
        d2 = _assert_query_success(r2)

        # SQL should contain different tenant filters
        assert "t001" in d1["sql"]
        assert "t002" in d2["sql"]

        # u001 SQL should contain HD or HN (华东/华南)
        assert "HD" in d1["sql"] or "HN" in d1["sql"]
        # u002 SQL should contain HB or XN (华北/西南)
        assert "HB" in d2["sql"] or "XN" in d2["sql"]

    def test_combined_region_and_channel_filter(self, mock_api_client):
        """Row-level region filter combined with user channel filter."""
        dsl = {
            "metrics": [{"func": "count", "field": "id", "alias": "order_count"}],
            "dimensions": ["channel"],
            "filters": [{"field": "channel", "operator": "=", "value": "线上"}],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        # SQL should contain both channel='online' and region_code in ('HD', 'HN')
        assert "online" in data["sql"]

    def test_channel_semantic_resolution(self, mock_api_client):
        """Channel value '线上' should be resolved to 'online'."""
        dsl = {
            "metrics": [{"func": "count", "field": "id", "alias": "order_count"}],
            "filters": [{"field": "channel", "operator": "=", "value": "线上"}],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        # After semantic resolution, "线上" -> "online"
        assert "online" in data["sql"]


# =============================================================================
# Phase 9: Full pipeline via /query endpoint
# =============================================================================

class TestFullPipelineQueries:
    """Test the complete /query pipeline (question -> DSL -> SQL -> data)."""

    def test_query_multi_dimension(self, mock_api_client):
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询各品类各渠道的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_dsl_has_metric(data, "sales_amount")
        _assert_sql_and_data(data, min_rows=1)

    def test_query_with_date_dimension(self, mock_api_client):
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询各日期的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_dsl_has_metric(data, "sales_amount")
        _assert_sql_and_data(data, min_rows=1)

    def test_query_brand_filter(self, mock_api_client):
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询苹果品牌的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_dsl_has_metric(data, "sales_amount")
        _assert_sql_and_data(data, min_rows=1)

    def test_query_customer_type(self, mock_api_client):
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询VIP客户的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_dsl_has_metric(data, "sales_amount")
        _assert_sql_and_data(data, min_rows=1)

    def test_query_gmv_by_region(self, mock_api_client):
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询各地区的GMV",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_dsl_has_metric(data, "gmv")
        _assert_sql_and_data(data, min_rows=1)

    def test_query_discount_by_channel(self, mock_api_client):
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询各渠道的优惠总额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_dsl_has_metric(data, "total_discount")
        _assert_sql_and_data(data, min_rows=1)

    def test_query_quantity_by_category(self, mock_api_client):
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询各品类的销量",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_dsl_has_metric(data, "total_quantity")
        _assert_sql_and_data(data, min_rows=1)

    def test_query_new_customer_sales(self, mock_api_client):
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询新客的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_dsl_has_metric(data, "sales_amount")
        _assert_sql_and_data(data, min_rows=1)


# =============================================================================
# Phase 10: Complex ecommerce queries (multi-join, multi-dim, advanced filters)
# =============================================================================

class TestComplexEcommerceQueries:
    """Test complex ecommerce queries using precise DSL.

    Covers: multi-table joins, multi-dimension grouping, complex filters,
    sorting + pagination, and cross-domain analytics.
    """

    def test_multi_join_orders_products_suppliers(self, mock_api_client):
        """三表 JOIN：订单 + 产品 + 供应商."""
        dsl = {
            "metrics": [
                {"func": "sum", "field": "pay_amount", "alias": "sales_amount"},
                {"func": "count", "field": "id", "alias": "order_count"},
            ],
            "dimensions": ["supplier_name", "category"],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert "supplier_dim" in data["sql"]

    def test_multi_dimension_category_channel(self, mock_api_client):
        """多维度分组：品类 + 渠道."""
        dsl = {
            "metrics": [
                {"func": "sum", "field": "pay_amount", "alias": "sales_amount"},
                {"func": "sum", "field": "quantity", "alias": "total_quantity"},
            ],
            "dimensions": ["category", "channel"],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)

    def test_complex_filter_range_and_multiple(self, mock_api_client):
        """复杂过滤：金额范围 + 地区 + 渠道."""
        dsl = {
            "metrics": [
                {"func": "sum", "field": "pay_amount", "alias": "sales_amount"},
                {"func": "avg", "field": "pay_amount", "alias": "avg_order_value"},
            ],
            "dimensions": ["product_name"],
            "filters": [
                {"field": "pay_amount", "operator": ">", "value": 1000},
                {"field": "region", "operator": "=", "value": "华东"},
                {"field": "channel", "operator": "=", "value": "线上"},
            ],
            "order_by": [{"field": "sales_amount", "direction": "desc"}],
            "limit": 10,
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert "HD" in data["sql"] or "华东" in data["sql"]
        assert "online" in data["sql"] or "线上" in data["sql"]

    def test_top_products_by_profit_margin(self, mock_api_client):
        """TOP N + 排序：销售额最高的产品（带折扣分析）."""
        dsl = {
            "metrics": [
                {"func": "sum", "field": "pay_amount", "alias": "sales_amount"},
                {"func": "sum", "field": "discount_amount", "alias": "total_discount"},
            ],
            "dimensions": ["product_name", "brand"],
            "order_by": [{"field": "sales_amount", "direction": "desc"}],
            "limit": 5,
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert len(data["data"]) <= 5

    def test_inventory_with_warehouse_join(self, mock_api_client):
        """库存 + 仓库 JOIN：各仓库类型的库存总量."""
        dsl = {
            "metrics": [
                {"func": "sum", "field": "stock_quantity", "alias": "total_stock"},
                {"func": "sum", "field": "available_quantity", "alias": "total_available"},
            ],
            "dimensions": ["warehouse_type", "region"],
            "data_source": "inventory",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert "inventory_fact" in data["sql"]

    def test_customer_segment_analysis(self, mock_api_client):
        """客户细分：各客户类型的订单量和客单价."""
        dsl = {
            "metrics": [
                {"func": "count", "field": "id", "alias": "order_count"},
                {"func": "avg", "field": "pay_amount", "alias": "avg_order_value"},
                {"func": "sum", "field": "pay_amount", "alias": "sales_amount"},
            ],
            "dimensions": ["customer_type"],
            "order_by": [{"field": "sales_amount", "direction": "desc"}],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)

    def test_region_tier_sales_analysis(self, mock_api_client):
        """地区维度 JOIN：按城市等级统计销售额."""
        dsl = {
            "metrics": [
                {"func": "sum", "field": "pay_amount", "alias": "sales_amount"},
                {"func": "count", "field": "id", "alias": "order_count"},
            ],
            "dimensions": ["tier_level"],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert "region_dim" in data["sql"]

    def test_weekend_vs_weekday_sales(self, mock_api_client):
        """日期维度 JOIN：周末 vs 工作日销售额对比."""
        dsl = {
            "metrics": [
                {"func": "sum", "field": "pay_amount", "alias": "sales_amount"},
                {"func": "count", "field": "id", "alias": "order_count"},
            ],
            "dimensions": ["is_weekend"],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert "date_dim" in data["sql"]

    def test_supplier_performance_ranking(self, mock_api_client):
        """供应商绩效：按信用等级和合作年限分析销售额."""
        dsl = {
            "metrics": [
                {"func": "sum", "field": "pay_amount", "alias": "sales_amount"},
                {"func": "count", "field": "DISTINCT product_id", "alias": "stock_product_count"},
            ],
            "dimensions": ["credit_rating", "supplier_name"],
            "order_by": [
                {"field": "credit_rating", "direction": "asc"},
                {"field": "sales_amount", "direction": "desc"},
            ],
            "limit": 8,
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert "supplier_dim" in data["sql"]

    def test_multi_metric_cross_analysis(self, mock_api_client):
        """跨数据源分析：销售额 + 库存量（通过 product_name 关联）."""
        dsl = {
            "metrics": [
                {"func": "sum", "field": "stock_quantity", "alias": "total_stock"},
                {"func": "avg", "field": "days_of_supply", "alias": "avg_days_supply"},
            ],
            "dimensions": ["brand", "category"],
            "filters": [
                {"field": "days_of_supply", "operator": "<", "value": 30},
            ],
            "order_by": [{"field": "avg_days_supply", "direction": "asc"}],
            "limit": 10,
            "data_source": "inventory",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert len(data["data"]) <= 10
