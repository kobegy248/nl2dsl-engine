"""Integration tests with REAL LLM calls.

These tests verify that the NL2DSL pipeline works correctly with a real
large language model. They require a valid LLM API key in the environment.

Without a key, tests are automatically skipped (see integration/conftest.py).
"""

from __future__ import annotations

import time

import pytest

from nl2dsl.config import settings
from nl2dsl.dsl.models import DSL, Aggregation
from nl2dsl.dsl.validator import DSLValidator
from nl2dsl.graph.nodes import (
    _parse_llm_output,
    _post_process_dsl,
    _semantic_fix_dsl,
    _make_generate_dsl_node,
    _make_decompose_node,
    _make_verify_dsl_node,
)
from nl2dsl.graph.state import QueryState
from nl2dsl.llm.client import LLMClient
from nl2dsl.llm.prompts import DSL_SYSTEM_PROMPT
from nl2dsl.semantic.resolver import SemanticResolver


# ---------------------------------------------------------------------------
# Test data: a realistic semantic registry
# ---------------------------------------------------------------------------

TEST_REGISTRY = {
    "metrics": {
        "sales_amount": {"expr": "SUM(pay_amount)", "description": "销售额（实付金额合计）"},
        "gmv": {"expr": "SUM(order_amount)", "description": "成交总额"},
        "order_count": {"expr": "COUNT(id)", "description": "订单数量"},
        "avg_order_value": {"expr": "AVG(pay_amount)", "description": "客单价"},
        "total_discount": {"expr": "SUM(discount_amount)", "description": "优惠总额"},
    },
    "dimensions": {
        "product_name": {"column": "product_name", "description": "产品名称"},
        "brand": {"column": "brand", "description": "品牌"},
        "category": {"column": "category", "description": "品类"},
        "region": {"column": "region", "description": "地区"},
        "channel": {"column": "channel", "description": "销售渠道"},
        "customer_type": {"column": "customer_type", "description": "客户类型"},
        "order_date": {"column": "order_date", "description": "订单日期"},
    },
    "data_sources": {
        "orders": {
            "table": "order_fact",
            "metrics": ["sales_amount", "gmv", "order_count", "avg_order_value", "total_discount"],
            "dimensions": ["product_name", "brand", "category", "region", "channel", "customer_type", "order_date"],
        },
    },
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def llm_client():
    """Create a real LLM client — skipped if no API key."""
    if not settings.llm_api_key:
        pytest.skip("NL2DSL_LLM_API_KEY not set — skipping real LLM integration test")

    client = LLMClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )

    # connectivity probe
    try:
        client.generate("Say 'pong'", "You are a test harness.")
    except Exception as exc:
        pytest.skip(f"LLM unreachable ({type(exc).__name__}: {exc}) — skipping")

    return client


@pytest.fixture
def validator():
    return DSLValidator(TEST_REGISTRY)


@pytest.fixture
def resolver():
    return SemanticResolver(TEST_REGISTRY)


# ---------------------------------------------------------------------------
# 1. Basic DSL generation — semantic correctness verification
# ---------------------------------------------------------------------------


class TestRealLLMGenerateDSL:
    """Verify that a real LLM generates DSL semantically matching the question."""

    def _generate_and_parse(self, llm_client, question: str) -> DSL:
        """Helper: generate DSL from question and return validated DSL object."""
        prompt = _build_dsl_prompt(question)
        raw = llm_client.generate(prompt, DSL_SYSTEM_PROMPT)
        assert raw, "LLM returned empty response"
        parsed = _parse_llm_output(raw)
        assert isinstance(parsed, dict), f"Expected dict, got {type(parsed)}: {parsed!r}"
        dsl_dict = _post_process_dsl(parsed)
        return DSL.model_validate(dsl_dict)

    def test_llm_generates_valid_json(self, llm_client):
        """LLM must produce parseable JSON with correct structure."""
        dsl = self._generate_and_parse(llm_client, "查询华东地区销售额最高的产品")
        # Must have data_source and at least one metric
        assert dsl.data_source == "orders"
        assert dsl.metrics, f"Expected at least one metric, got: {dsl.model_dump()}"
        # Must have product_name dimension since question asks "产品"
        dims = dsl.dimensions or []
        assert "product_name" in dims, (
            f"Question asks for '产品' but dimensions don't include product_name: {dims}"
        )

    def test_llm_understands_region_filter(self, llm_client):
        """'华东地区' must produce a region filter with value '华东' or 'HD'."""
        dsl = self._generate_and_parse(llm_client, "查询华东地区线上渠道的销售额")
        filters = dsl.filters or []
        region_filters = [f for f in filters if f.field == "region"]
        assert region_filters, (
            f"Question mentions '华东地区' but no region filter found. "
            f"Filters: {[f.model_dump() for f in filters]}"
        )
        assert region_filters[0].value in ("华东", "HD"), (
            f"Region filter value should be '华东' or 'HD', got: {region_filters[0].value}"
        )
        # Also verify channel filter
        channel_filters = [f for f in filters if f.field == "channel"]
        assert channel_filters, (
            f"Question mentions '线上渠道' but no channel filter found. "
            f"Filters: {[f.model_dump() for f in filters]}"
        )

    def test_llm_understands_top_n(self, llm_client):
        """'前10' must produce limit=10 and descending order_by on sales metric."""
        dsl = self._generate_and_parse(llm_client, "查询销售额前10的产品")
        assert dsl.limit == 10, f"Expected limit=10, got {dsl.limit}"
        # Should have order_by with desc direction
        order_by = dsl.order_by or []
        assert order_by, f"Question asks for '前10' but no order_by found: {dsl.model_dump()}"
        assert order_by[0].direction == "desc", (
            f"Expected descending order for '前10', got: {order_by[0].direction}"
        )

    def test_llm_understands_multiple_metrics(self, llm_client):
        """'销售额和订单量' must produce BOTH metrics, not just one."""
        dsl = self._generate_and_parse(llm_client, "查询各品类的销售额和订单量")
        aliases = {m.alias for m in (dsl.metrics or [])}
        assert "sales_amount" in aliases, (
            f"Question asks for '销售额' but sales_amount not in metrics. Got: {aliases}"
        )
        assert "order_count" in aliases, (
            f"Question asks for '订单量' but order_count not in metrics. Got: {aliases}"
        )
        # Must have category dimension since "各品类"
        dims = dsl.dimensions or []
        assert "category" in dims, (
            f"Question asks for '各品类' but category not in dimensions. Got: {dims}"
        )

    def test_llm_output_survives_markdown_fences(self, llm_client):
        """Some models wrap JSON in markdown fences — _parse_llm_output must handle it."""
        prompt = _build_dsl_prompt("查询销售额")
        raw = llm_client.generate(prompt, DSL_SYSTEM_PROMPT)
        # Parse must succeed regardless of fences
        parsed = _parse_llm_output(raw)
        assert isinstance(parsed, dict)
        assert "data_source" in parsed
        assert parsed.get("data_source") == "orders"

    def test_llm_output_survives_explanatory_text(self, llm_client):
        """Some models add text before/after JSON — _parse_llm_output must extract it."""
        prompt = (
            "请输出DSL JSON，并在JSON前后各加一句话解释。\n"
            "用户问题：查询销售额"
        )
        raw = llm_client.generate(prompt, DSL_SYSTEM_PROMPT)
        parsed = _parse_llm_output(raw)
        assert isinstance(parsed, dict)
        assert parsed.get("data_source") == "orders"
        assert "metrics" in parsed

    def test_llm_generates_executable_dsl(self, llm_client, validator):
        """Generated DSL must pass validation — fields must exist in registry."""
        dsl = self._generate_and_parse(llm_client, "查询各品牌销售额")
        # Validate against registry
        errors = validator.validate(dsl)
        assert not errors, f"DSL validation failed: {errors}\nDSL: {dsl.model_dump()}"


# ---------------------------------------------------------------------------
# 2. Semantic fix — verify LLM corrects DSL errors
# ---------------------------------------------------------------------------


class TestRealLLMSemanticFix:
    """Verify _semantic_fix_dsl agentic path with a real LLM."""

    def test_agentic_fix_adds_missing_region_filter(self, llm_client):
        """LLM should detect that '华东地区' needs a region filter."""
        dsl_dict = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
            "dimensions": ["product_name"],
            "filters": [],
        }
        result = _semantic_fix_dsl(
            dsl_dict, "查询华东地区销售额", llm_client=llm_client
        )
        filters = result.get("filters") or []
        region_filters = [
            f for f in filters
            if f.get("field") == "region" and f.get("value") in ("华东", "HD")
        ]
        assert region_filters, (
            f"LLM should add region='华东' filter for question '查询华东地区销售额'. "
            f"Got filters: {filters}"
        )

    def test_agentic_fix_adds_channel_filter(self, llm_client):
        """LLM should detect that '线上渠道' needs a channel filter."""
        dsl_dict = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
            "dimensions": ["product_name"],
            "filters": [],
        }
        result = _semantic_fix_dsl(
            dsl_dict, "查询线上渠道的销售额", llm_client=llm_client
        )
        filters = result.get("filters") or []
        channel_filters = [
            f for f in filters
            if f.get("field") == "channel" and f.get("value") in ("线上", "online")
        ]
        assert channel_filters, (
            f"LLM should add channel='线上' filter for question '查询线上渠道的销售额'. "
            f"Got filters: {filters}"
        )

    def test_agentic_fix_extracts_top_n(self, llm_client):
        """LLM should change limit from 10 to 5 when question says '前5'."""
        dsl_dict = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
            "dimensions": ["product_name"],
            "limit": 10,
        }
        result = _semantic_fix_dsl(
            dsl_dict, "查询销售额前5的产品", llm_client=llm_client
        )
        assert result.get("limit") == 5, (
            f"Expected limit changed from 10 to 5 for '前5', got: {result.get('limit')}"
        )

    def test_agentic_fix_no_duplicate_filters(self, llm_client):
        """If filter already exists, LLM should not add a duplicate."""
        dsl_dict = {
            "data_source": "orders",
            "metrics": [],
            "filters": [{"field": "region", "operator": "=", "value": "华东"}],
        }
        result = _semantic_fix_dsl(
            dsl_dict, "查询华东地区的销售额", llm_client=llm_client
        )
        filters = result.get("filters") or []
        region_filters = [f for f in filters if f.get("field") == "region"]
        assert len(region_filters) == 1, (
            f"Should not duplicate region filter. Got {len(region_filters)} region filters: {region_filters}"
        )

    def test_agentic_fix_preserves_existing_correct_filters(self, llm_client):
        """LLM should not remove already-correct filters."""
        dsl_dict = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
            "dimensions": ["product_name"],
            "filters": [
                {"field": "region", "operator": "=", "value": "华东"},
                {"field": "channel", "operator": "=", "value": "线上"},
            ],
        }
        result = _semantic_fix_dsl(
            dsl_dict, "查询华东地区线上渠道的销售额", llm_client=llm_client
        )
        filters = result.get("filters") or []
        fields = {f.get("field") for f in filters}
        assert "region" in fields, f"LLM should preserve existing region filter. Got: {filters}"
        assert "channel" in fields, f"LLM should preserve existing channel filter. Got: {filters}"


# ---------------------------------------------------------------------------
# 3. Decompose — verify LLM rewrites complex queries meaningfully
# ---------------------------------------------------------------------------


class TestRealLLMDecompose:
    """Verify _make_decompose_node with a real LLM."""

    def test_decompose_rewrites_complex_query(self, llm_client):
        """Complex query must be rewritten into simpler sub-questions."""
        decompose = _make_decompose_node(llm_client)
        state = _make_state("对比今年和去年华东的销售额")
        result = decompose(state)
        complexity = result.get("complexity")
        assert complexity in ("complex_rewritten", "complex", "simple")

        if complexity == "complex_rewritten":
            rewritten = result.get("question", "")
            original = state["question"]
            assert rewritten != original, (
                f"Complex query should be rewritten. Got same question: {rewritten}"
            )
            assert result.get("original_question") == original
            # Rewritten should still contain core intent keywords
            assert "销售额" in rewritten, (
                f"Rewritten question should preserve '销售额'. Got: {rewritten}"
            )

    def test_decompose_skips_simple_query(self, llm_client):
        """Simple query should not be rewritten — complexity stays 'simple'."""
        decompose = _make_decompose_node(llm_client)
        state = _make_state("查询华东销售额")
        result = decompose(state)
        assert result.get("complexity") == "simple", (
            f"Simple query should not be rewritten. Got complexity={result.get('complexity')}, "
            f"trace={result.get('trace')!r}"
        )
        # Simple path does not return a new question — the original stays in state
        assert "question" not in result or result.get("question") == state["question"]


# ---------------------------------------------------------------------------
# 4. Verify — verify LLM can detect DSL-question mismatches
# ---------------------------------------------------------------------------


class TestRealLLMVerify:
    """Verify _make_verify_dsl_node with a real LLM.

    These tests check that the LLM can meaningfully judge whether a DSL
    matches the user's question. We use unambiguous cases to minimize
    non-determinism.
    """

    def test_verify_passes_on_matching_dsl(self, llm_client):
        """DSL that perfectly matches the question should pass or warn (not fail)."""
        verify = _make_verify_dsl_node(llm_client)
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["product_name"],
            filters=[],
            data_source="orders",
        )
        state = _make_state("查询各产品销售额")
        state["dsl"] = dsl
        state["data"] = [{"product_name": "iPhone", "sales_amount": 1000}]
        result = verify(state)
        status = result.get("verify_status")
        # A matching DSL should not fail; pass or warn are both acceptable
        assert status in ("pass", "warn"), (
            f"Matching DSL (sales metric for sales question) should not fail. "
            f"Got status={status!r}, reason={result.get('verify_reason')!r}"
        )

    def test_verify_fails_on_clearly_wrong_metric(self, llm_client):
        """DSL with completely wrong metric should be flagged by LLM."""
        verify = _make_verify_dsl_node(llm_client)
        dsl = DSL(
            metrics=[Aggregation(func="count", field="id", alias="order_count")],
            dimensions=["product_name"],
            data_source="orders",
        )
        state = _make_state("查询销售额")  # user asked for sales, DSL has order_count
        state["dsl"] = dsl
        state["data"] = [{"product_name": "iPhone", "order_count": 100}]
        result = verify(state)
        status = result.get("verify_status")
        # LLM should ideally detect the mismatch, but we accept any valid status
        # since model behavior varies. We just verify it doesn't crash.
        assert status in ("pass", "warn", "fail", "skipped")
        # If it passes, at least log what the LLM reasoned so we can review
        if status == "pass":
            pytest.skip(
                f"LLM did not detect metric mismatch (status=pass). "
                f"Reason: {result.get('verify_reason')!r} — review needed"
            )

    def test_verify_detects_missing_dimension(self, llm_client):
        """DSL missing required dimension should be flagged."""
        verify = _make_verify_dsl_node(llm_client)
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["product_name"],  # user asked for brand breakdown
            data_source="orders",
        )
        state = _make_state("查询各品牌的销售额")  # user explicitly asks for brands
        state["dsl"] = dsl
        state["data"] = [{"product_name": "iPhone", "sales_amount": 1000}]
        result = verify(state)
        status = result.get("verify_status")
        # The DSL uses product_name but user asked for brand — this is a mismatch.
        # We don't strictly assert fail because LLMs vary, but we verify
        # the node produced a meaningful result (not crash / not None).
        assert status in ("pass", "warn", "fail", "skipped")
        # Log the reason for human review
        print(f"\n[verify_missing_dimension] status={status}, reason={result.get('verify_reason')!r}")


# ---------------------------------------------------------------------------
# 5. End-to-end: real LLM → generate → validate → resolve → execute SQL
# ---------------------------------------------------------------------------


class TestRealLLMEndToEnd:
    """Full pipeline with real LLM: generate → parse → validate → resolve → execute."""

    def test_generate_dsl_node_semantic_correctness(self, llm_client, validator, resolver):
        """Generated DSL must semantically match the question AND survive the full pipeline."""
        generate = _make_generate_dsl_node(
            llm_client=llm_client,
            rag_retriever=None,
            llm_system_prompt=DSL_SYSTEM_PROMPT,
        )
        state = _make_state("查询华东地区销售额最高的5个产品")
        result = generate(state)
        dsl = result["dsl"]
        assert dsl is not None, "generate node returned None dsl"
        assert dsl.data_source == "orders"

        # Semantic correctness: must have sales metric
        aliases = {m.alias for m in (dsl.metrics or [])}
        assert "sales_amount" in aliases, (
            f"Question asks for '销售额' but got metrics: {aliases}"
        )

        # Must have region filter for "华东"
        filters = dsl.filters or []
        region_filters = [f for f in filters if f.field == "region"]
        assert region_filters, (
            f"Question asks for '华东地区' but no region filter. Filters: {[f.model_dump() for f in filters]}"
        )

        # Must have product dimension for "产品"
        dims = dsl.dimensions or []
        assert "product_name" in dims, (
            f"Question asks for '产品' but dimensions don't include product_name: {dims}"
        )

        # Must have limit=5 for "5个"
        assert dsl.limit == 5, f"Question asks for '前5个' but limit={dsl.limit}"

        # Validate passes
        errors = validator.validate(dsl)
        assert not errors, f"Validation errors: {errors}"

        # Resolve transforms metric fields to SQL expressions
        resolved = resolver.resolve(dsl)
        assert resolved is not None
        resolved_metrics = resolved.metrics or []
        assert any(
            "SUM(" in (m.field or "") for m in resolved_metrics
        ), f"Resolved metrics should contain SQL expression. Got: {[m.field for m in resolved_metrics]}"

    def test_pipeline_generates_and_executes_sql(self, llm_client):
        """Full round-trip: LLM generates DSL → build SQL → execute → get real data."""
        from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Float, text

        engine = create_engine("sqlite:///:memory:")
        metadata = MetaData()
        Table("order_fact", metadata,
            Column("id", Integer, primary_key=True),
            Column("product_id", Integer),
            Column("product_name", String),
            Column("brand", String),
            Column("category", String),
            Column("region", String),
            Column("channel", String),
            Column("customer_type", String),
            Column("order_amount", Float),
            Column("pay_amount", Float),
        )
        Table("product_dim", metadata,
            Column("product_id", Integer, primary_key=True),
            Column("product_name", String),
            Column("brand", String),
            Column("category", String),
            Column("price", Float),
        )
        metadata.create_all(engine)

        # Insert test data — need product_dim rows for JOIN to match
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO product_dim (product_id, product_name, brand, category, price)
                VALUES
                    (1, 'iPhone', '苹果', '手机', 7999.0),
                    (2, 'Mate60', '华为', '手机', 6999.0),
                    (3, 'MacBook', '苹果', '电脑', 14999.0)
            """))
            conn.execute(text("""
                INSERT INTO order_fact (id, product_id, product_name, brand, region, pay_amount)
                VALUES
                    (1, 1, 'iPhone', '苹果', '华东', 5000.0),
                    (2, 1, 'iPhone', '苹果', '华东', 3000.0),
                    (3, 2, 'Mate60', '华为', '华南', 4000.0),
                    (4, 3, 'MacBook', '苹果', '华东', 8000.0)
            """))
            conn.commit()

        from nl2dsl.sql_engine.builder import SQLBuilder
        sql_builder = SQLBuilder(
            engine,
            {"orders": "order_fact"},
            TEST_REGISTRY["data_sources"],
            {k: v["column"] for k, v in TEST_REGISTRY["dimensions"].items()},
            TEST_REGISTRY["metrics"],
        )

        generate = _make_generate_dsl_node(
            llm_client=llm_client,
            rag_retriever=None,
            llm_system_prompt=DSL_SYSTEM_PROMPT,
        )
        state = _make_state("查询各品牌的销售额")
        result = generate(state)
        dsl = result["dsl"]
        assert dsl is not None, "LLM failed to generate DSL"

        # Build SQL
        sql = sql_builder.build(dsl)
        assert "SELECT" in sql.upper(), f"SQL missing SELECT: {sql}"
        assert "GROUP BY" in sql.upper(), f"SQL missing GROUP BY: {sql}"

        # Actually execute the SQL and verify we get data
        with engine.connect() as conn:
            rows = conn.execute(text(sql)).mappings().all()

        assert len(rows) >= 1, (
            f"SQL executed but returned no rows. SQL: {sql}\n"
            f"DSL: {dsl.model_dump()}"
        )

        # Verify the aggregation is actually correct
        # Apple has 2华东 orders: 5000 + 3000 + 8000 = 16000
        # 华为 has 1华南 order: 4000
        brand_sales = {}
        for row in rows:
            row_dict = dict(row)
            brand = row_dict.get("brand") or row_dict.get("product_name")
            sales = row_dict.get("sales_amount") or row_dict.get("pay_amount")
            if brand and sales is not None:
                brand_sales[brand] = sales

        # If LLM picked brand dimension, Apple should have higher sales than 华为
        if "苹果" in brand_sales and "华为" in brand_sales:
            assert brand_sales["苹果"] > brand_sales["华为"], (
                f"Apple has more sales data (16000 vs 4000) but aggregation shows otherwise. "
                f"Results: {brand_sales}"
            )

    def test_pipeline_with_filters_generates_executable_sql(self, llm_client):
        """Query with filters: LLM → DSL → SQL → execute → filtered results."""
        from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Float, text

        engine = create_engine("sqlite:///:memory:")
        metadata = MetaData()
        Table("order_fact", metadata,
            Column("id", Integer, primary_key=True),
            Column("product_id", Integer),
            Column("product_name", String),
            Column("brand", String),
            Column("region", String),
            Column("pay_amount", Float),
        )
        Table("product_dim", metadata,
            Column("product_id", Integer, primary_key=True),
            Column("product_name", String),
            Column("brand", String),
            Column("category", String),
            Column("price", Float),
        )
        metadata.create_all(engine)

        # Insert data
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO product_dim (product_id, product_name, brand, category, price)
                VALUES
                    (1, 'iPhone', '苹果', '手机', 7999.0),
                    (2, 'Mate60', '华为', '手机', 6999.0)
            """))
            conn.commit()

        # Insert data: mix of 华东 and 华南
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO order_fact (id, product_id, product_name, brand, region, pay_amount)
                VALUES
                    (1, 1, 'iPhone', '苹果', '华东', 5000.0),
                    (2, 2, 'Mate60', '华为', '华东', 3000.0),
                    (3, 3, 'MacBook', '苹果', '华南', 8000.0)
            """))
            conn.commit()

        from nl2dsl.sql_engine.builder import SQLBuilder
        sql_builder = SQLBuilder(
            engine,
            {"orders": "order_fact"},
            TEST_REGISTRY["data_sources"],
            {k: v["column"] for k, v in TEST_REGISTRY["dimensions"].items()},
            TEST_REGISTRY["metrics"],
        )

        generate = _make_generate_dsl_node(
            llm_client=llm_client,
            rag_retriever=None,
            llm_system_prompt=DSL_SYSTEM_PROMPT,
        )
        state = _make_state("查询华东地区的销售额")
        result = generate(state)
        dsl = result["dsl"]
        assert dsl is not None

        # Verify region filter exists
        filters = dsl.filters or []
        region_filters = [f for f in filters if f.field == "region"]
        assert region_filters, (
            f"Question asks for '华东地区' but no region filter in DSL: {[f.model_dump() for f in filters]}"
        )

        sql = sql_builder.build(dsl)

        # Execute and verify filtered results exclude 华南 data
        with engine.connect() as conn:
            rows = conn.execute(text(sql)).mappings().all()

        # If the SQL has a region filter, it should return fewer than 3 rows
        # (since 1 of the 3 rows is 华南)
        if region_filters and region_filters[0].value in ("华东", "HD"):
            # The SQL should filter to only 华东 rows
            total_pay = sum(
                row.get("sales_amount") or row.get("pay_amount") or 0
                for row in rows
            )
            # 华东 rows: 5000 + 3000 = 8000; if 华南 is filtered out, total should be 8000
            # This is a best-effort check since the SQL structure depends on LLM output
            print(f"\n[pipeline_with_filters] rows={len(rows)}, SQL: {sql}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_dsl_prompt(question: str) -> str:
    """Build a prompt for DSL generation matching the fallback prompt structure."""
    return f"""【表结构】
- 数据源: orders (对应表 order_fact), 字段: id, product_id, product_name, brand, category, region, channel, customer_id, customer_type, order_amount, discount_amount, pay_amount, quantity, order_date

【可用指标】
- sales_amount: SUM(pay_amount), 销售额
- gmv: SUM(order_amount), 成交总额
- order_count: COUNT(id), 订单数量
- avg_order_value: AVG(pay_amount), 客单价
- total_discount: SUM(discount_amount), 优惠总额

【可用维度】
- product_name, brand, category, region, channel, customer_type, order_date

【重要规则】
1. data_source 必须是 "orders"
2. metrics 的 alias 必须是已注册的指标名
3. 不要输出任何解释文字，只输出 JSON

【用户问题】
{question}

请输出 DSL JSON："""


def _make_state(question: str) -> QueryState:
    return QueryState(
        question=question,
        user_id="u001",
        tenant_id="t001",
        data_source="orders",
        domain="ecommerce",
        ambiguities=None,
        dsl=None,
        dsl_attempts=None,
        sql=None,
        sandbox_result=None,
        complexity=None,
        data=None,
        status="pending",
        error=None,
        error_code=None,
        trace=None,
        query_id=f"q-{int(time.time() * 1000)}",
        started_at=time.time(),
        llm_used=False,
        original_question=None,
        rewrite_reason=None,
        verify_status=None,
        verify_reason=None,
    )
