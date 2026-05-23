import pytest
from unittest.mock import MagicMock

from nl2dsl.dsl.generator import (
    RuleBasedDSLGenerator,
    RetryChain,
    MaxRetryExceeded,
    DSLGenerator,
)
from nl2dsl.dsl.models import DSL, Aggregation
from nl2dsl.exceptions import ValidationError


class TestRuleBasedDSLGenerator:
    def test_sales_keyword(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("查询销售额")
        assert isinstance(dsl, DSL)
        assert dsl.metrics[0].alias == "sales_amount"
        assert dsl.data_source == "orders"

    def test_gmv_keyword(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("查询GMV")
        assert dsl.metrics[0].alias == "gmv"

    def test_order_count_keyword(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("查询订单量")
        assert dsl.metrics[0].alias == "order_count"
        assert dsl.metrics[0].func == "count"

    def test_avg_order_value(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("查询客单价")
        assert dsl.metrics[0].alias == "avg_order_value"
        assert dsl.metrics[0].func == "avg"

    def test_default_metric(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("随便问一个问题")
        assert dsl.metrics[0].alias == "sales_amount"

    def test_dimension_product(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("按产品查询")
        assert "product_name" in dsl.dimensions

    def test_dimension_region(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("按地区查询")
        assert "region" in dsl.dimensions

    def test_default_dimension(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("查询销售额")
        assert dsl.dimensions == ["product_name"]

    def test_filter_region(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("查询华东地区的销售额")
        assert any(f.field == "region" and f.value == "华东" for f in dsl.filters)

    def test_filter_channel(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("查询线上渠道的销售额")
        assert any(f.field == "channel" and f.value == "线上" for f in dsl.filters)

    def test_filter_category(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("查询手机品类的销售额")
        assert any(f.field == "category" and f.value == "手机" for f in dsl.filters)

    def test_limit_top(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("查询销售额最高的产品")
        assert dsl.limit == 10

    def test_limit_all(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("查询所有产品的销售额")
        assert dsl.limit == 100

    def test_data_source_override(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("查询", data_source="custom")
        assert dsl.data_source == "custom"

    def test_order_by_first_metric(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("查询销售额")
        assert dsl.order_by[0].field == "sales_amount"
        assert dsl.order_by[0].direction == "desc"

    def test_registry_passed(self):
        reg = {"metrics": {"test": {}}}
        gen = RuleBasedDSLGenerator(registry=reg)
        # registry 当前未被使用，但应能正常初始化
        dsl = gen.generate("查询")
        assert isinstance(dsl, DSL)


class TestRetryChain:
    def test_success_no_retry(self):
        mock_gen = MagicMock(spec=DSLGenerator)
        mock_gen.generate.return_value = DSL(data_source="orders")

        chain = RetryChain(mock_gen, max_retries=3)
        result = chain.generate("查询销售额")

        assert result.data_source == "orders"
        mock_gen.generate.assert_called_once()

    def test_retry_then_success(self):
        mock_gen = MagicMock(spec=DSLGenerator)
        mock_gen.generate.side_effect = [
            ValueError("bad"),
            DSL(data_source="orders"),
        ]

        chain = RetryChain(mock_gen, max_retries=3)
        result = chain.generate("查询销售额")

        assert result.data_source == "orders"
        assert mock_gen.generate.call_count == 2

    def test_max_retry_exceeded(self):
        mock_gen = MagicMock(spec=DSLGenerator)
        mock_gen.generate.side_effect = ValueError("always fails")

        chain = RetryChain(mock_gen, max_retries=2)
        with pytest.raises(MaxRetryExceeded) as exc_info:
            chain.generate("查询销售额")

        assert "always fails" in str(exc_info.value)
        assert mock_gen.generate.call_count == 2

    def test_validator_passes(self):
        mock_gen = MagicMock(spec=DSLGenerator)
        mock_gen.generate.return_value = DSL(data_source="orders")
        validator = MagicMock()

        chain = RetryChain(mock_gen, validator=validator, max_retries=2)
        result = chain.generate("查询销售额")

        validator.assert_called_once()
        assert result.data_source == "orders"

    def test_validator_fails_then_retry(self):
        mock_gen = MagicMock(spec=DSLGenerator)
        mock_gen.generate.return_value = DSL(data_source="orders")
        validator = MagicMock(side_effect=[ValidationError("invalid"), None])

        chain = RetryChain(mock_gen, validator=validator, max_retries=2)
        result = chain.generate("查询销售额")

        assert validator.call_count == 2
        assert result.data_source == "orders"

    def test_error_feedback_in_prompt(self):
        mock_gen = MagicMock(spec=DSLGenerator)
        mock_gen.generate.side_effect = [
            ValueError("missing field"),
            DSL(data_source="orders"),
        ]

        chain = RetryChain(mock_gen, max_retries=3)
        chain.generate("查询销售额")

        second_call = mock_gen.generate.call_args_list[1]
        prompt = second_call[0][0]
        assert "missing field" in prompt
        assert "Previous attempts failed" in prompt

    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            DSLGenerator()
