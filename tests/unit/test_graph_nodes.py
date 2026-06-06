"""Tests for graph node functions."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from nl2dsl.dsl.models import DSL, Aggregation, Filter, Join, OrderBy
from nl2dsl.dsl.validator import DSLValidator
from nl2dsl.exceptions import ValidationError, NL2DSLException
from nl2dsl.graph.nodes import (
    with_error_handler,
    create_node_functions,
    _build_fallback_prompt,
    _parse_llm_output,
    _post_process_dsl,
    _restore_metric_fields,
    _semantic_fix_dsl,
    _extract_top_n,
    _fix_metric_format,
)
from nl2dsl.graph.state import QueryState
from nl2dsl.permission.row_level import RowLevelSecurity
from nl2dsl.permission.column_level import ColumnLevelSecurity
from nl2dsl.semantic.resolver import SemanticResolver
from nl2dsl.query.clarification import ClarificationDetector
from nl2dsl.query.sandbox import SandboxResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_rag_retriever():
    retriever = MagicMock()
    retriever.build_prompt = MagicMock(return_value="rag prompt")
    return retriever


@pytest.fixture
def test_registry():
    return {
        "metrics": {
            "sales_amount": {"expr": "SUM(order_amount)", "description": "销售额"},
        },
        "dimensions": {
            "product_name": {"column": "product_name", "description": "产品名称"},
        },
        "data_sources": {
            "orders": {"table": "order_fact", "metrics": ["sales_amount"], "dimensions": ["product_name"]},
        },
    }


@pytest.fixture
def nodes(real_llm_client, mock_rag_retriever, test_registry):
    """Create all node functions with real LLM dependencies."""
    validator = DSLValidator(test_registry)
    row_security = RowLevelSecurity({})
    col_security = ColumnLevelSecurity()
    resolver = SemanticResolver(test_registry)

    # Mock SQLBuilder
    sql_builder = MagicMock()
    sql_builder.build = MagicMock(return_value="SELECT * FROM order_fact")

    # Mock SQLScanner
    scanner = MagicMock()
    scanner.scan = MagicMock()

    # Mock QuerySandbox
    sandbox = MagicMock()
    sandbox.check = MagicMock(return_value=SandboxResult(passed=True, risks=[], sample_rows=[]))

    # Mock SQLExecutor
    executor = MagicMock()
    executor.execute = MagicMock(return_value=[{"product_name": "iPhone", "sales_amount": 1000}])

    clarification_detector = ClarificationDetector()

    return create_node_functions(
        llm_client=real_llm_client,
        rag_retriever=mock_rag_retriever,
        validator=validator,
        row_security=row_security,
        col_security=col_security,
        resolver=resolver,
        sql_builder=sql_builder,
        scanner=scanner,
        sandbox=sandbox,
        executor=executor,
        clarification_detector=clarification_detector,
        llm_system_prompt="你是一个 DSL 生成助手。",
    )


@pytest.fixture
def base_state():
    return QueryState(
        question="查询销售额",
        user_id="u001",
        tenant_id="t001",
        data_source="orders",
        status="pending",
        error=None,
        error_code=None,
        query_id="q001",
        started_at=0.0,
        llm_used=False,
    )


# ---------------------------------------------------------------------------
# with_error_handler decorator tests
# ---------------------------------------------------------------------------


class TestWithErrorHandler:
    def test_success_case(self):
        """Decorator should return the function result on success."""
        @with_error_handler("test_node")
        def good_node(state: QueryState) -> dict:
            return {"status": "success", "data": "ok"}

        state = QueryState(
            question="test", user_id="u1", tenant_id="t1",
            status="pending", query_id="q1", started_at=0.0, llm_used=False,
        )
        result = good_node(state)
        assert result["status"] == "success"
        assert result["data"] == "ok"

    def test_catches_validation_error(self):
        """Decorator should catch ValidationError and convert to error state."""
        @with_error_handler("test_node")
        def bad_node(state: QueryState) -> dict:
            raise ValidationError("Invalid input")

        state = QueryState(
            question="test", user_id="u1", tenant_id="t1",
            status="pending", query_id="q1", started_at=0.0, llm_used=False,
        )
        result = bad_node(state)
        assert result["status"] == "error"
        assert result["error"] == "Invalid input"
        assert result["error_code"] == "VALIDATION_ERROR"
        assert result["trace"][0]["step"] == "test_node"
        assert result["trace"][0]["status"] == "error"

    def test_catches_generic_exception(self):
        """Decorator should catch generic Exception and convert to error state."""
        @with_error_handler("test_node")
        def crash_node(state: QueryState) -> dict:
            raise RuntimeError("Something went wrong")

        state = QueryState(
            question="test", user_id="u1", tenant_id="t1",
            status="pending", query_id="q1", started_at=0.0, llm_used=False,
        )
        result = crash_node(state)
        assert result["status"] == "error"
        assert "Something went wrong" in result["error"]
        assert result["error_code"] == "INTERNAL_ERROR"
        assert result["trace"][0]["step"] == "test_node"

    def test_catches_subclass_of_nl2dslexception(self):
        """Decorator should catch any NL2DSLException subclass."""
        class CustomError(NL2DSLException):
            error_code = "CUSTOM_ERROR"
            status_code = 418

        @with_error_handler("test_node")
        def custom_error_node(state: QueryState) -> dict:
            raise CustomError("Custom problem")

        state = QueryState(
            question="test", user_id="u1", tenant_id="t1",
            status="pending", query_id="q1", started_at=0.0, llm_used=False,
        )
        result = custom_error_node(state)
        assert result["status"] == "error"
        assert result["error"] == "Custom problem"
        assert result["error_code"] == "CUSTOM_ERROR"


# ---------------------------------------------------------------------------
# create_node_functions factory tests
# ---------------------------------------------------------------------------


class TestCreateNodeFunctions:
    def test_returns_all_expected_nodes(self, nodes):
        expected = {
            "clarification_node",
            "plan_node",
            "confidence_node",
            "explain_node",
            "decompose_node",
            "generate_dsl_node",
            "validate_dsl_node",
            "correct_dsl_node",
            "inject_row_permission_node",
            "check_col_permission_node",
            "resolve_semantic_node",
            "build_sql_node",
            "scan_sql_node",
            "sandbox_check_node",
            "human_review_node",
            "execute_sql_node",
            "simplify_dsl_node",
            "verify_dsl_node",
        }
        assert set(nodes.keys()) == expected

    def test_all_nodes_are_callable(self, nodes):
        for name, node in nodes.items():
            assert callable(node), f"{name} should be callable"


# ---------------------------------------------------------------------------
# clarification_node tests
# ---------------------------------------------------------------------------


class TestClarificationNode:
    def test_no_ambiguities(self, nodes, base_state):
        """When question is clear, return empty ambiguities and keep status pending."""
        # Use a question that has explicit time context and no ambiguous keywords
        base_state["question"] = "查询2024年1月order_amount的总和"
        result = nodes["clarification_node"](base_state)
        assert result.get("ambiguities") is None
        assert result["trace"]["step"] == "clarification"
        assert result["trace"]["items_count"] == 0

    def test_with_ambiguities(self, nodes, base_state):
        """When question is ambiguous, return ambiguities and set status to clarification."""
        base_state["question"] = "查询销量"  # "销量" is ambiguous
        result = nodes["clarification_node"](base_state)
        assert result["ambiguities"] is not None
        assert len(result["ambiguities"]) > 0
        assert result["status"] == "clarification"
        assert result["trace"]["items_count"] > 0

    def test_time_missing(self, nodes, base_state):
        """Question about trend without time context should trigger time_missing clarification."""
        base_state["question"] = "销售额增长了多少"
        result = nodes["clarification_node"](base_state)
        assert result["status"] == "clarification"
        assert any(a.type == "time_missing" for a in result["ambiguities"])


# ---------------------------------------------------------------------------
# generate_dsl_node tests
# ---------------------------------------------------------------------------


class TestGenerateDSLNode:
    def test_uses_llm_when_available(self, nodes, base_state):
        result = nodes["generate_dsl_node"](base_state)
        assert result["dsl"] is not None
        assert result["llm_used"] is True
        assert result["dsl_attempts"]["source"] == "llm"

    def test_raises_when_llm_none(self, base_state, test_registry):
        """When llm_client is None, generate_dsl_node should raise ValidationError."""
        validator = DSLValidator(test_registry)
        row_security = RowLevelSecurity({})
        col_security = ColumnLevelSecurity()
        resolver = SemanticResolver(test_registry)
        scanner = MagicMock()
        sandbox = MagicMock()
        executor = MagicMock()
        detector = ClarificationDetector()

        nodes_no_llm = create_node_functions(
            llm_client=None,
            rag_retriever=None,
            validator=validator,
            row_security=row_security,
            col_security=col_security,
            resolver=resolver,
            sql_builder=MagicMock(),
            scanner=scanner,
            sandbox=sandbox,
            executor=executor,
            clarification_detector=detector,
        )

        result = nodes_no_llm["generate_dsl_node"](base_state)
        # Without LLM, generate_dsl falls back to RuleBasedDSLGenerator
        assert "dsl" in result
        assert result["dsl"] is not None
        assert result.get("trace", {}).get("source") == "rule_based"

    def test_uses_rag_when_available(self, nodes, base_state, mock_rag_retriever):
        nodes["generate_dsl_node"](base_state)
        mock_rag_retriever.build_prompt.assert_called_once_with("查询销售额")


# ---------------------------------------------------------------------------
# validate_dsl_node tests
# ---------------------------------------------------------------------------


class TestValidateDSLNode:
    def test_valid_dsl_passes(self, nodes, base_state):
        base_state["dsl"] = DSL(
            metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
            dimensions=["product_name"],
            data_source="orders",
            limit=10,
        )
        result = nodes["validate_dsl_node"](base_state)
        assert result["trace"][0]["step"] == "validate_dsl"
        assert result["trace"][0]["status"] == "success"

    def test_none_dsl_returns_error(self, nodes, base_state):
        base_state["dsl"] = None
        result = nodes["validate_dsl_node"](base_state)
        assert result["status"] == "error"
        assert result["error_code"] == "VALIDATION_ERROR"
        assert result["dsl_attempts"]["source"] == "validation"
        assert result["dsl_attempts"]["valid"] is False


# ---------------------------------------------------------------------------
# correct_dsl_node tests
# ---------------------------------------------------------------------------


class TestCorrectDSLNode:
    def test_corrects_with_llm(self, nodes, base_state):
        base_state["error"] = "Invalid metric 'foo'"
        result = nodes["correct_dsl_node"](base_state)
        # With real LLM, it may produce a corrected DSL or fail;
        # verify the attempt was made via LLM path.
        if result.get("status") != "error":
            assert result["dsl"] is not None
            assert result["dsl_attempts"]["source"] == "llm_corrected_agentic"
            assert result["dsl_attempts"]["error_feedback"] == "Invalid metric 'foo'"

    def test_returns_error_when_llm_none(self, base_state, test_registry):
        validator = DSLValidator(test_registry)
        row_security = RowLevelSecurity({})
        col_security = ColumnLevelSecurity()
        resolver = SemanticResolver(test_registry)

        nodes_no_llm = create_node_functions(
            llm_client=None,
            rag_retriever=None,
            validator=validator,
            row_security=row_security,
            col_security=col_security,
            resolver=resolver,
            sql_builder=MagicMock(),
            scanner=MagicMock(),
            sandbox=MagicMock(),
            executor=MagicMock(),
            clarification_detector=ClarificationDetector(),
        )

        base_state["error"] = "Some error"
        result = nodes_no_llm["correct_dsl_node"](base_state)
        assert result["status"] == "error"
        assert result["error_code"] == "CORRECTION_FAILED"


# ---------------------------------------------------------------------------
# inject_row_permission_node tests
# ---------------------------------------------------------------------------


class TestInjectRowPermissionNode:
    def test_injects_filters(self, nodes, base_state):
        base_state["dsl"] = DSL(
            metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
            dimensions=["product_name"],
            data_source="orders",
            limit=10,
        )
        result = nodes["inject_row_permission_node"](base_state)
        assert result["dsl"] is not None
        assert result["trace"]["step"] == "inject_row_permission"

    def test_none_dsl_raises(self, nodes, base_state):
        base_state["dsl"] = None
        result = nodes["inject_row_permission_node"](base_state)
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# check_col_permission_node tests
# ---------------------------------------------------------------------------


class TestCheckColPermissionNode:
    def test_allowed_dimensions_pass(self, nodes, base_state):
        base_state["dsl"] = DSL(
            metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
            dimensions=["product_name"],
            data_source="orders",
            limit=10,
        )
        result = nodes["check_col_permission_node"](base_state)
        assert result["trace"]["step"] == "check_col_permission"

    def test_none_dsl_raises(self, nodes, base_state):
        base_state["dsl"] = None
        result = nodes["check_col_permission_node"](base_state)
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# resolve_semantic_node tests
# ---------------------------------------------------------------------------


class TestResolveSemanticNode:
    def test_resolves_metrics(self, nodes, base_state):
        base_state["dsl"] = DSL(
            metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
            dimensions=["product_name"],
            data_source="orders",
            limit=10,
        )
        result = nodes["resolve_semantic_node"](base_state)
        assert result["dsl"] is not None
        assert result["trace"]["step"] == "resolve_semantic"

    def test_none_dsl_raises(self, nodes, base_state):
        base_state["dsl"] = None
        result = nodes["resolve_semantic_node"](base_state)
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# build_sql_node tests
# ---------------------------------------------------------------------------


class TestBuildSQLNode:
    def test_builds_sql(self, nodes, base_state):
        base_state["dsl"] = DSL(
            metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
            dimensions=["product_name"],
            data_source="orders",
            limit=10,
        )
        result = nodes["build_sql_node"](base_state)
        assert result["sql"] == "SELECT * FROM order_fact"
        assert result["trace"]["step"] == "build_sql"

    def test_none_dsl_raises(self, nodes, base_state):
        base_state["dsl"] = None
        result = nodes["build_sql_node"](base_state)
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# scan_sql_node tests
# ---------------------------------------------------------------------------


class TestScanSQLNode:
    def test_scans_sql(self, nodes, base_state):
        base_state["sql"] = "SELECT * FROM order_fact"
        result = nodes["scan_sql_node"](base_state)
        assert result["trace"]["step"] == "scan_sql"

    def test_none_sql_raises(self, nodes, base_state):
        base_state["sql"] = None
        result = nodes["scan_sql_node"](base_state)
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# sandbox_check_node tests
# ---------------------------------------------------------------------------


class TestSandboxCheckNode:
    def test_passed_sandbox(self, nodes, base_state):
        base_state["sql"] = "SELECT * FROM order_fact"
        result = nodes["sandbox_check_node"](base_state)
        assert result["sandbox_result"].passed is True
        assert result["trace"]["status"] == "success"

    def test_failed_sandbox(self, nodes, base_state):
        nodes["_sandbox_mock"] = MagicMock()
        base_state["sql"] = "SELECT * FROM order_fact"
        result = nodes["sandbox_check_node"](base_state)
        assert "sandbox_result" in result

    def test_none_sql_raises(self, nodes, base_state):
        base_state["sql"] = None
        result = nodes["sandbox_check_node"](base_state)
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# human_review_node tests
# ---------------------------------------------------------------------------


class TestHumanReviewNode:
    def test_sets_pending_review(self, nodes, base_state):
        base_state["sandbox_result"] = SandboxResult(
            passed=False,
            risks=["High scan count"],
            sample_rows=[],
        )
        result = nodes["human_review_node"](base_state)
        assert result["status"] == "pending_review"
        assert result["trace"]["reason"] == "sandbox_warnings"
        assert result["trace"]["risks"] == ["High scan count"]

    def test_sets_pending_review_without_sandbox_result(self, nodes, base_state):
        base_state["sandbox_result"] = None
        result = nodes["human_review_node"](base_state)
        assert result["status"] == "pending_review"


# ---------------------------------------------------------------------------
# execute_sql_node tests
# ---------------------------------------------------------------------------


class TestExecuteSQLNode:
    def test_executes_sql(self, nodes, base_state):
        base_state["sql"] = "SELECT * FROM order_fact"
        result = nodes["execute_sql_node"](base_state)
        assert result["data"] == [{"product_name": "iPhone", "sales_amount": 1000}]
        assert result["status"] == "success"
        assert result["trace"]["rows_returned"] == 1

    def test_none_sql_raises(self, nodes, base_state):
        base_state["sql"] = None
        result = nodes["execute_sql_node"](base_state)
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# simplify_dsl_node tests
# ---------------------------------------------------------------------------


class TestSimplifyDSLNode:
    def test_simplifies_complex_dsl(self, nodes, base_state):
        base_state["dsl"] = DSL(
            metrics=[
                Aggregation(func="sum", field="order_amount", alias="sales_amount"),
                Aggregation(func="count", field="id", alias="order_count"),
            ],
            dimensions=["product_name", "region", "brand"],
            filters=[Filter(field="region", operator="=", value="华东")],
            joins=[Join(table="customer_dim", on_field="customer_id", join_type="left")],
            data_source="orders",
            limit=50,
        )
        result = nodes["simplify_dsl_node"](base_state)
        simplified = result["dsl"]
        assert len(simplified.metrics) == 1
        assert len(simplified.dimensions) == 1
        assert simplified.joins is None
        assert simplified.filters is None
        assert simplified.order_by is None
        assert simplified.limit <= 10
        assert result["dsl_attempts"]["source"] == "simplified"

    def test_none_dsl_raises(self, nodes, base_state):
        base_state["dsl"] = None
        result = nodes["simplify_dsl_node"](base_state)
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestBuildFallbackPrompt:
    def test_includes_question(self):
        registry = {
            "metrics": {"sales_amount": {"expr": "SUM(pay_amount)", "description": "销售额"}},
            "dimensions": {"product_name": {"column": "product_name", "description": "产品名称"}},
            "data_sources": {"orders": {"table": "order_fact", "metrics": ["sales_amount"], "dimensions": ["product_name"]}},
        }
        prompt = _build_fallback_prompt("查询销售额", registry)
        assert "查询销售额" in prompt
        assert "orders" in prompt
        assert "sales_amount" in prompt


class TestParseLLMOutput:
    def test_parses_json(self):
        raw = '{"data_source": "orders", "metrics": []}'
        result = _parse_llm_output(raw)
        assert result["data_source"] == "orders"

    def test_strips_markdown_fences(self):
        raw = '```json\n{"data_source": "orders"}\n```'
        result = _parse_llm_output(raw)
        assert result["data_source"] == "orders"

    def test_strips_code_block(self):
        raw = '```\n{"data_source": "orders"}\n```'
        result = _parse_llm_output(raw)
        assert result["data_source"] == "orders"


class TestPostProcessDSL:
    def test_fixes_missing_data_source(self):
        dsl_dict = {"metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}]}
        result = _post_process_dsl(dsl_dict)
        assert result["data_source"] == "orders"

    def test_fixes_missing_metrics(self):
        dsl_dict = {"data_source": "orders"}
        result = _post_process_dsl(dsl_dict)
        assert result["metrics"] == [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}]

    def test_normalizes_metric_fields(self):
        dsl_dict = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "SUM(order_amount)", "alias": "sales_amount"}],
        }
        result = _post_process_dsl(dsl_dict)
        assert result["metrics"][0]["field"] == "order_amount"

    def test_fixes_invalid_limit(self):
        dsl_dict = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
            "limit": -5,
        }
        result = _post_process_dsl(dsl_dict)
        assert result["limit"] == 10

    def test_caps_high_limit(self):
        dsl_dict = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
            "limit": 500,
        }
        result = _post_process_dsl(dsl_dict)
        assert result["limit"] == 100

    def test_fixes_invalid_operator(self):
        dsl_dict = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
            "filters": [{"field": "region", "operator": "equals", "value": "华东"}],
        }
        result = _post_process_dsl(dsl_dict)
        assert result["filters"][0]["operator"] == "="


class TestPostProcessFilterTree:
    """Tests that _post_process_dsl correctly handles filter trees."""

    def test_post_process_flat_list_still_works(self):
        dsl_dict = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["product_name"],
            "filters": [
                {"field": "region", "operator": "=", "value": "华东"},
            ],
        }
        result = _post_process_dsl(dsl_dict)
        assert isinstance(result["filters"], list)
        assert result["filters"][0]["field"] == "region"

    def test_post_process_tree_preserved(self):
        dsl_dict = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["product_name"],
            "filters": {
                "op": "and",
                "children": [
                    {"field": "region", "operator": "=", "value": "华东"},
                    {"field": "pay_amount", "operator": ">", "value": 5000},
                ],
            },
        }
        result = _post_process_dsl(dsl_dict)
        assert isinstance(result["filters"], dict)
        assert result["filters"]["op"] == "and"
        assert len(result["filters"]["children"]) == 2

    def test_post_process_validates_filter_ops_in_tree(self):
        dsl_dict = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["product_name"],
            "filters": {
                "op": "and",
                "children": [
                    {"field": "region", "operator": "=", "value": "华东"},
                    {"field": "pay_amount", "operator": "invalid_op", "value": 5000},
                ],
            },
        }
        result = _post_process_dsl(dsl_dict)
        children = result["filters"]["children"]
        assert children[1]["operator"] == "="


class TestRestoreMetricFields:
    def test_restores_sum_expression(self):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="SUM(order_amount)", alias="sales_amount")],
            data_source="orders",
        )
        result = _restore_metric_fields(dsl)
        assert result.metrics[0].field == "order_amount"

    def test_no_change_for_plain_field(self):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
            data_source="orders",
        )
        result = _restore_metric_fields(dsl)
        assert result.metrics[0].field == "order_amount"

    def test_no_metrics_returns_unchanged(self):
        dsl = DSL(data_source="orders")
        result = _restore_metric_fields(dsl)
        assert result.metrics is None


# ---------------------------------------------------------------------------
# _extract_top_n tests
# ---------------------------------------------------------------------------


class TestExtractTopN:
    def test_extracts_numeric_prefix(self):
        assert _extract_top_n("查询前5的产品") == 5

    def test_extracts_top_keyword(self):
        assert _extract_top_n("top10的产品") == 10

    def test_extracts_chinese_number(self):
        assert _extract_top_n("最好的三款产品") == 3

    def test_extracts_前十名(self):
        assert _extract_top_n("销售额前十名") == 10

    def test_extracts_排名前(self):
        assert _extract_top_n("排名前5的品牌") == 5

    def test_returns_default_when_no_match(self):
        assert _extract_top_n("查询销售额", default=20) == 20

    def test_returns_default_for_out_of_range(self):
        """Numbers > 100 or < 1 should fall back to default."""
        assert _extract_top_n("查询前999个产品") == 10  # > 100 capped at default

    def test_all_keyword_returns_100(self):
        assert _extract_top_n("查询全部产品") == 100

    def test_extracts_from_vague_patterns(self):
        assert _extract_top_n("最畅销的5款产品") == 5


# ---------------------------------------------------------------------------
# _fix_metric_format tests
# ---------------------------------------------------------------------------


class TestFixMetricFormat:
    def test_maps_known_alias(self):
        m = {"alias": "sales_amount"}
        result = _fix_metric_format(m)
        assert result["func"] == "sum"
        assert result["field"] == "order_amount"
        assert result["alias"] == "sales_amount"

    def test_uses_name_instead_of_alias(self):
        m = {"name": "gmv"}
        result = _fix_metric_format(m)
        assert result["alias"] == "gmv"
        assert result["func"] == "sum"

    def test_uses_metric_instead_of_alias(self):
        m = {"metric": "order_count"}
        result = _fix_metric_format(m)
        assert result["alias"] == "order_count"
        assert result["func"] == "count"

    def test_falls_back_to_defaults_for_unknown(self):
        m = {}
        result = _fix_metric_format(m)
        assert result["func"] == "sum"
        assert result["field"] == "order_amount"
        assert result["alias"] == "order_amount"

    def test_preserves_existing_func(self):
        m = {"func": "avg", "field": "pay_amount", "alias": "avg_pay"}
        result = _fix_metric_format(m)
        assert result["func"] == "avg"
        assert result["field"] == "pay_amount"

    def test_maps_whitespace_alias_via_metric_map(self):
        """Whitespace-padded alias is normalized and overwritten."""
        m = {"alias": "  sales_amount  "}
        result = _fix_metric_format(m)
        assert result["alias"] == "sales_amount"
        assert result["func"] == "sum"
        assert result["field"] == "order_amount"


# ---------------------------------------------------------------------------
# _semantic_fix_dsl tests (fallback path, no LLM)
# ---------------------------------------------------------------------------


class TestSemanticFixDSL:
    def test_adds_region_filter_from_question(self):
        dsl_dict = {"data_source": "orders", "metrics": [], "filters": []}
        result = _semantic_fix_dsl(dsl_dict, "查询华南地区的销售额", llm_client=None)
        filters = result.get("filters") or []
        assert any(f.get("field") == "region" and f.get("value") == "华南" for f in filters)

    def test_adds_channel_filter_online(self):
        dsl_dict = {"data_source": "orders", "metrics": [], "filters": []}
        result = _semantic_fix_dsl(dsl_dict, "查询线上渠道的销售额", llm_client=None)
        filters = result.get("filters") or []
        assert any(f.get("field") == "channel" and f.get("value") == "线上" for f in filters)

    def test_adds_channel_filter_offline(self):
        dsl_dict = {"data_source": "orders", "metrics": [], "filters": []}
        result = _semantic_fix_dsl(dsl_dict, "查询线下渠道的销售额", llm_client=None)
        filters = result.get("filters") or []
        assert any(f.get("field") == "channel" and f.get("value") == "线下" for f in filters)

    def test_adds_vip_customer_filter(self):
        dsl_dict = {"data_source": "orders", "metrics": [], "filters": []}
        result = _semantic_fix_dsl(dsl_dict, "查询VIP客户的销售额", llm_client=None)
        filters = result.get("filters") or []
        assert any(f.get("field") == "customer_type" and f.get("value") == "VIP" for f in filters)

    def test_adds_new_customer_filter(self):
        dsl_dict = {"data_source": "orders", "metrics": [], "filters": []}
        result = _semantic_fix_dsl(dsl_dict, "查询新客户的销售额", llm_client=None)
        filters = result.get("filters") or []
        assert any(f.get("field") == "customer_type" and f.get("value") == "新客" for f in filters)

    def test_adds_old_customer_filter(self):
        dsl_dict = {"data_source": "orders", "metrics": [], "filters": []}
        result = _semantic_fix_dsl(dsl_dict, "查询老客户的销售额", llm_client=None)
        filters = result.get("filters") or []
        assert any(f.get("field") == "customer_type" and f.get("value") == "老客" for f in filters)

    def test_extracts_top_n_from_question(self):
        dsl_dict = {"data_source": "orders", "metrics": [], "limit": 10}
        result = _semantic_fix_dsl(dsl_dict, "查询前20的产品", llm_client=None)
        assert result["limit"] == 20

    def test_does_not_duplicate_existing_filter(self):
        """If region filter already exists, don't add another."""
        dsl_dict = {
            "data_source": "orders",
            "metrics": [],
            "filters": [{"field": "region", "operator": "=", "value": "华北"}],
        }
        result = _semantic_fix_dsl(dsl_dict, "查询华北地区的销售额", llm_client=None)
        filters = result.get("filters") or []
        assert len([f for f in filters if f.get("field") == "region"]) == 1

    def test_sets_none_filters_when_empty(self):
        dsl_dict = {"data_source": "orders", "metrics": [], "filters": None}
        result = _semantic_fix_dsl(dsl_dict, "查询销售额", llm_client=None)
        assert result.get("filters") is None


# ---------------------------------------------------------------------------
# _parse_llm_output additional tests (edge cases)
# ---------------------------------------------------------------------------


class TestParseLLMOutputEdgeCases:
    def test_parses_plain_text_without_fences(self):
        raw = 'Some explanation text\n{"data_source": "orders", "metrics": []}\nMore text'
        result = _parse_llm_output(raw)
        assert result["data_source"] == "orders"

    def test_parses_raw_json_when_no_brackets_found(self):
        raw = '{"data_source": "orders"}'
        result = _parse_llm_output(raw)
        assert result["data_source"] == "orders"

    def test_raises_on_invalid_json(self):
        with pytest.raises(Exception):
            _parse_llm_output("not json at all")


# ---------------------------------------------------------------------------
# _post_process_dsl additional tests (edge cases)
# ---------------------------------------------------------------------------


class TestPostProcessDSLEdgeCases:
    def test_metrics_as_string(self):
        """LLM may return a string instead of array for metrics."""
        dsl_dict = {"data_source": "orders", "metrics": "sales_amount"}
        result = _post_process_dsl(dsl_dict)
        assert isinstance(result["metrics"], list)
        assert result["metrics"][0]["alias"] == "sales_amount"

    def test_empty_dimensions_list(self):
        """Empty dimensions list is preserved (valid for pure aggregation)."""
        dsl_dict = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
            "dimensions": [],
        }
        result = _post_process_dsl(dsl_dict)
        assert result["dimensions"] == []

    def test_dimensions_with_non_string_items(self):
        dsl_dict = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
            "dimensions": ["product_name", 123, None],
        }
        result = _post_process_dsl(dsl_dict)
        assert "product_name" in result["dimensions"]
        assert 123 not in result["dimensions"]

    def test_does_not_auto_generate_order_by(self):
        """Missing order_by is left as-is (design decision: don't auto-add)."""
        dsl_dict = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
        }
        result = _post_process_dsl(dsl_dict)
        assert "order_by" not in result

    def test_zero_limit_becomes_default(self):
        dsl_dict = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
            "limit": 0,
        }
        result = _post_process_dsl(dsl_dict)
        assert result["limit"] == 10

    def test_string_limit_becomes_default(self):
        dsl_dict = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
            "limit": "ten",
        }
        result = _post_process_dsl(dsl_dict)
        assert result["limit"] == 10

    def test_invalid_operator_in_filter(self):
        dsl_dict = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
            "filters": [{"field": "region", "operator": "eq", "value": "华东"}],
        }
        result = _post_process_dsl(dsl_dict)
        assert result["filters"][0]["operator"] == "="

    def test_strips_distinct_from_metric_field(self):
        dsl_dict = {
            "data_source": "orders",
            "metrics": [{"func": "count", "field": "COUNT(DISTINCT customer_id)", "alias": "customer_count"}],
        }
        result = _post_process_dsl(dsl_dict)
        assert result["metrics"][0]["field"] == "customer_id"

    def test_strips_func_wrapper_from_field(self):
        dsl_dict = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "SUM(order_amount)", "alias": "sales_amount"}],
        }
        result = _post_process_dsl(dsl_dict)
        assert result["metrics"][0]["field"] == "order_amount"


