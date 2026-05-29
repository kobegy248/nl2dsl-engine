"""End-to-end tests for bank domain queries.

Tests the full pipeline with bank-specific data: customer accounts,
transactions, product agreements, and organizational hierarchy.
"""

from __future__ import annotations

import pytest


def _assert_query_success(response):
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data.get("status") == "success", f"Expected status='success', got: {data}"
    return data


def _assert_sql_and_data(data, min_rows: int = 0):
    sql = data.get("sql")
    assert sql is not None and "SELECT" in sql, f"SQL should contain SELECT, got: {sql}"
    rows = data.get("data", [])
    assert len(rows) >= min_rows, f"Expected at least {min_rows} rows, got {len(rows)}"


# =============================================================================
# Phase 1: Basic bank queries (via /query/execute with exact DSL)
# =============================================================================

class TestBankBasicQueries:
    """Test basic bank queries using precise DSL."""

    def test_query_total_balance(self, bank_api_client):
        """查询总余额."""
        dsl = {
            "metrics": [{"func": "sum", "field": "acct_bal", "alias": "total_balance"}],
            "data_source": "customer_accounts",
        }
        response = bank_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl, "user_id": "b003", "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert "t_acct_main" in data["sql"]

    def test_query_customer_count(self, bank_api_client):
        """查询客户数量."""
        dsl = {
            "metrics": [{"func": "count", "field": "DISTINCT cif_no", "alias": "customer_count"}],
            "data_source": "customers",
        }
        response = bank_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl, "user_id": "b003", "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)

    def test_query_account_count(self, bank_api_client):
        """查询账户数量."""
        dsl = {
            "metrics": [{"func": "count", "field": "DISTINCT acct_no", "alias": "account_count"}],
            "data_source": "customer_accounts",
        }
        response = bank_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl, "user_id": "b003", "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)

    def test_query_transaction_count(self, bank_api_client):
        """查询交易笔数."""
        dsl = {
            "metrics": [{"func": "count", "field": "txn_seq_no", "alias": "txn_count"}],
            "data_source": "transactions",
        }
        response = bank_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl, "user_id": "b003", "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)


class TestBankDimensionQueries:
    """Test bank queries with dimension grouping."""

    def test_query_balance_by_account_type(self, bank_api_client):
        """按账户类型统计余额."""
        dsl = {
            "metrics": [{"func": "sum", "field": "acct_bal", "alias": "total_balance"}],
            "dimensions": ["account_type"],
            "data_source": "customer_accounts",
        }
        response = bank_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl, "user_id": "b003", "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)

    def test_query_customers_by_risk_level(self, bank_api_client):
        """按风险等级统计客户数."""
        dsl = {
            "metrics": [{"func": "count", "field": "DISTINCT cif_no", "alias": "customer_count"}],
            "dimensions": ["risk_level"],
            "data_source": "customers",
        }
        response = bank_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl, "user_id": "b003", "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)

    def test_query_txn_by_channel(self, bank_api_client):
        """按渠道统计交易金额."""
        dsl = {
            "metrics": [{"func": "sum", "field": "txn_amt", "alias": "txn_amount"}],
            "dimensions": ["channel_name"],
            "data_source": "transactions",
        }
        response = bank_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl, "user_id": "b003", "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert "t_chl_mapping" in data["sql"]

    def test_query_balance_by_org(self, bank_api_client):
        """按机构统计余额（JOIN t_org_hier）."""
        dsl = {
            "metrics": [{"func": "sum", "field": "acct_bal", "alias": "total_balance"}],
            "dimensions": ["org_name"],
            "data_source": "customer_accounts",
        }
        response = bank_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl, "user_id": "b003", "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert "t_org_hier" in data["sql"]


class TestBankFilterQueries:
    """Test bank queries with filters."""

    def test_query_current_account_balance(self, bank_api_client):
        """查询活期存款余额."""
        dsl = {
            "metrics": [{"func": "sum", "field": "acct_bal", "alias": "total_balance"}],
            "filters": [{"field": "account_type", "operator": "=", "value": "01"}],
            "data_source": "customer_accounts",
        }
        response = bank_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl, "user_id": "b003", "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)

    def test_query_normal_customers(self, bank_api_client):
        """查询正常状态客户."""
        dsl = {
            "metrics": [{"func": "count", "field": "DISTINCT cif_no", "alias": "customer_count"}],
            "filters": [{"field": "customer_status", "operator": "=", "value": "01"}],
            "data_source": "customers",
        }
        response = bank_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl, "user_id": "b003", "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)

    def test_query_cny_accounts(self, bank_api_client):
        """查询人民币账户."""
        dsl = {
            "metrics": [{"func": "sum", "field": "acct_bal", "alias": "total_balance"}],
            "filters": [{"field": "currency", "operator": "=", "value": "CNY"}],
            "data_source": "customer_accounts",
        }
        response = bank_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl, "user_id": "b003", "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert "CNY" in data["sql"]


# =============================================================================
# Phase 2: Complex bank queries (multi-join, multi-metric, advanced filters)
# =============================================================================

class TestBankComplexQueries:
    """Test complex bank queries using precise DSL."""

    def test_multi_metric_multi_dimension_accounts(self, bank_api_client):
        """多指标 + 多维度：各机构各账户类型的余额和账户数."""
        dsl = {
            "metrics": [
                {"func": "sum", "field": "acct_bal", "alias": "total_balance"},
                {"func": "count", "field": "DISTINCT acct_no", "alias": "account_count"},
                {"func": "avg", "field": "acct_bal", "alias": "avg_balance"},
            ],
            "dimensions": ["org_name", "account_type"],
            "data_source": "customer_accounts",
        }
        response = bank_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl, "user_id": "b003", "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert "t_acct_main" in data["sql"]
        assert "t_org_hier" in data["sql"]

    def test_join_txn_with_channel_and_type(self, bank_api_client):
        """多表 JOIN：交易流水 + 渠道 + 交易类型."""
        dsl = {
            "metrics": [
                {"func": "count", "field": "txn_seq_no", "alias": "txn_count"},
                {"func": "sum", "field": "txn_amt", "alias": "txn_amount"},
            ],
            "dimensions": ["channel_name", "transaction_type_name"],
            "filters": [
                {"field": "reversal_flag", "operator": "=", "value": "0"},
            ],
            "data_source": "transactions",
        }
        response = bank_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl, "user_id": "b003", "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert "t_chl_mapping" in data["sql"]
        assert "t_txn_type_dict" in data["sql"]

    def test_agreement_with_product_join(self, bank_api_client):
        """合约 + 产品 JOIN：各产品类目的持有金额."""
        dsl = {
            "metrics": [
                {"func": "sum", "field": "hold_amt", "alias": "product_hold_amount"},
                {"func": "count", "field": "agt_no", "alias": "agreement_count"},
            ],
            "dimensions": ["product_level1_name", "product_level2_name"],
            "filters": [
                {"field": "agreement_status", "operator": "=", "value": "01"},
            ],
            "order_by": [{"field": "product_hold_amount", "direction": "desc"}],
            "limit": 10,
            "data_source": "agreements",
        }
        response = bank_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl, "user_id": "b003", "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert "t_prod_info" in data["sql"]
        assert "t_cif_base" in data["sql"]

    def test_inflow_outflow_comparison(self, bank_api_client):
        """流入流出对比：各渠道的流入和流出金额."""
        dsl = {
            "metrics": [
                {"func": "sum", "field": "CASE WHEN dr_cr_flg = '2' THEN txn_amt ELSE 0 END", "alias": "inflow_amount"},
                {"func": "sum", "field": "CASE WHEN dr_cr_flg = '1' THEN txn_amt ELSE 0 END", "alias": "outflow_amount"},
            ],
            "dimensions": ["channel_name"],
            "filters": [
                {"field": "reversal_flag", "operator": "=", "value": "0"},
            ],
            "data_source": "transactions",
        }
        response = bank_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl, "user_id": "b003", "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert "dr_cr_flg" in data["sql"]

    def test_top_accounts_by_balance(self, bank_api_client):
        """TOP N 查询：余额最高的账户."""
        dsl = {
            "metrics": [
                {"func": "sum", "field": "acct_bal", "alias": "total_balance"},
            ],
            "dimensions": ["customer_name", "account_type"],
            "order_by": [{"field": "total_balance", "direction": "desc"}],
            "limit": 5,
            "data_source": "customer_accounts",
        }
        response = bank_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl, "user_id": "b003", "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert len(data["data"]) <= 5

    def test_multi_filter_customer_accounts(self, bank_api_client):
        """多条件过滤：正常状态 + 人民币 + 活期."""
        dsl = {
            "metrics": [
                {"func": "sum", "field": "acct_bal", "alias": "total_balance"},
                {"func": "count", "field": "DISTINCT acct_no", "alias": "account_count"},
            ],
            "dimensions": ["customer_name"],
            "filters": [
                {"field": "account_status", "operator": "=", "value": "01"},
                {"field": "currency", "operator": "=", "value": "CNY"},
                {"field": "account_type", "operator": "=", "value": "01"},
            ],
            "data_source": "customer_accounts",
        }
        response = bank_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl, "user_id": "b003", "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert "CNY" in data["sql"]

    def test_customer_with_risk_and_org(self, bank_api_client):
        """客户 + 机构 JOIN：各机构各风险等级的客户数."""
        dsl = {
            "metrics": [
                {"func": "count", "field": "DISTINCT cif_no", "alias": "customer_count"},
            ],
            "dimensions": ["org_name", "risk_level"],
            "data_source": "customers",
        }
        response = bank_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl, "user_id": "b003", "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        assert "t_org_hier" in data["sql"]


# =============================================================================
# Phase 3: Permission isolation (row-level security)
# =============================================================================

class TestBankPermissionIsolation:
    """Test that row-level security isolates data per user."""

    def test_b001_only_sees_beijing(self, bank_api_client):
        """b001 只能看到北京分行的数据."""
        dsl = {
            "metrics": [{"func": "sum", "field": "acct_bal", "alias": "total_balance"}],
            "dimensions": ["org_name"],
            "data_source": "customer_accounts",
        }
        response = bank_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl, "user_id": "b001", "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        org_nms = {row.get("org_name") for row in data["data"]}
        for name in org_nms:
            assert "北京" in name, f"b001 should only see Beijing orgs, got: {name}"

    def test_b002_only_sees_shanghai(self, bank_api_client):
        """b002 只能看到上海分行的数据."""
        dsl = {
            "metrics": [{"func": "sum", "field": "acct_bal", "alias": "total_balance"}],
            "dimensions": ["org_name"],
            "data_source": "customer_accounts",
        }
        response = bank_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl, "user_id": "b002", "tenant_id": "t002",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        org_nms = {row.get("org_name") for row in data["data"]}
        for name in org_nms:
            assert "上海" in name, f"b002 should only see Shanghai orgs, got: {name}"

    def test_b003_sees_all_orgs(self, bank_api_client):
        """b003 无行级限制，可以看到所有机构."""
        dsl = {
            "metrics": [{"func": "sum", "field": "acct_bal", "alias": "total_balance"}],
            "dimensions": ["org_name"],
            "data_source": "customer_accounts",
        }
        response = bank_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl, "user_id": "b003", "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        _assert_sql_and_data(data, min_rows=1)
        org_nms = {row.get("org_name") for row in data["data"]}
        # Should see both Beijing and Shanghai orgs
        assert any("北京" in n for n in org_nms)
        assert any("上海" in n for n in org_nms)


# =============================================================================
# Phase 4: Management endpoints for bank domain
# =============================================================================

class TestBankManagementEndpoints:
    """Test schema/metrics endpoints return bank configuration."""

    def test_bank_schema_endpoint(self, bank_api_client):
        response = bank_api_client.get("/api/v1/schema")
        assert response.status_code == 200
        data = response.json()
        assert len(data["data_sources"]) > 0
        metric_names = {m["name"] for m in data["metrics"]}
        assert "total_balance" in metric_names
        assert "txn_amount" in metric_names

    def test_bank_metrics_endpoint(self, bank_api_client):
        response = bank_api_client.get("/api/v1/metrics")
        assert response.status_code == 200
        data = response.json()
        metric_names = {m["name"] for m in data["metrics"]}
        assert "customer_count" in metric_names
        assert "product_hold_amount" in metric_names
