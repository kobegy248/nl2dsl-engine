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

    def test_numeric_greater_than(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("价格大于5000的销售额")
        assert any(f.field == "price" and f.operator == ">" and f.value == 5000.0 for f in dsl.filters)

    def test_numeric_greater_equal(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("价格大于等于8000的销售额")
        assert any(f.field == "price" and f.operator == ">=" and f.value == 8000.0 for f in dsl.filters)

    def test_numeric_less_than(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("价格小于3000的销售额")
        assert any(f.field == "price" and f.operator == "<" and f.value == 3000.0 for f in dsl.filters)

    def test_range_between(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("价格在5000到20000之间的销售额")
        price_filters = [f for f in dsl.filters if f.field == "price"]
        assert len(price_filters) == 1
        assert price_filters[0].operator == "between"
        assert sorted(price_filters[0].value) == [5000.0, 20000.0]

    def test_range_between_swapped_bounds_normalized(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("价格在20000到5000之间的销售额")
        price_filters = [f for f in dsl.filters if f.field == "price"]
        assert price_filters[0].operator == "between"
        assert sorted(price_filters[0].value) == [5000.0, 20000.0]

    def test_negation_category_not_equal(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("非手机品类的销售额")
        cat_filters = [f for f in dsl.filters if f.field == "category"]
        assert len(cat_filters) == 1
        assert cat_filters[0].operator == "!="
        assert cat_filters[0].value == "手机"

    def test_negation_channel_not_equal(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("不是线上渠道的销售额")
        ch_filters = [f for f in dsl.filters if f.field == "channel"]
        assert len(ch_filters) == 1
        assert ch_filters[0].operator == "!="

    def test_group_top_n_post_process(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("查询各品类中销售额最高的产品")
        assert dsl.post_process.type == "group_top_n"
        assert dsl.post_process.group_by == ["category"]
        assert dsl.post_process.metric == "sales_amount"
        assert dsl.post_process.top_n == 1
        assert dsl.limit is None

    def test_proportion_post_process(self):
        gen = RuleBasedDSLGenerator()
        dsl = gen.generate("查询各品类销售额占总销售额的比例")
        assert dsl.post_process.type == "proportion"
        assert dsl.post_process.metric == "sales_amount"
        assert dsl.post_process.output_field == "sales_amount_proportion"
        assert dsl.limit is None


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
