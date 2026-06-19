import pytest
from nl2dsl.dsl.models import PostProcess
from nl2dsl.query.post_processor import (
    apply_post_process,
    calculate_proportion,
    extract_top_n_per_group,
    extract_top_per_group,
    should_post_process,
)


class TestExtractTopPerGroup:
    def test_basic_top_per_group(self):
        data = [
            {"category": "手机", "product_name": "iPhone", "sales_amount": 100000},
            {"category": "手机", "product_name": "Samsung", "sales_amount": 80000},
            {"category": "电脑", "product_name": "MacBook", "sales_amount": 120000},
            {"category": "电脑", "product_name": "Dell", "sales_amount": 60000},
            {"category": "耳机", "product_name": "AirPods", "sales_amount": 50000},
        ]
        result = extract_top_per_group(data, group_key="category", order_key="sales_amount")
        assert len(result) == 3
        categories = {r["category"] for r in result}
        assert categories == {"手机", "电脑", "耳机"}
        phone = next(r for r in result if r["category"] == "手机")
        assert phone["product_name"] == "iPhone"

    def test_ascending_order(self):
        data = [
            {"category": "A", "val": 100},
            {"category": "A", "val": 50},
            {"category": "B", "val": 200},
            {"category": "B", "val": 10},
        ]
        result = extract_top_per_group(data, group_key="category", order_key="val", order_desc=False)
        a = next(r for r in result if r["category"] == "A")
        assert a["val"] == 50

    def test_empty_data(self):
        result = extract_top_per_group([], group_key="x", order_key="y")
        assert result == []

    def test_single_group(self):
        data = [
            {"category": "A", "val": 100},
            {"category": "A", "val": 50},
        ]
        result = extract_top_per_group(data, group_key="category", order_key="val")
        assert len(result) == 1
        assert result[0]["val"] == 100

    def test_missing_order_key_defaults_to_zero(self):
        data = [
            {"category": "A", "product_name": "X"},
            {"category": "A", "product_name": "Y", "sales_amount": 100},
        ]
        result = extract_top_per_group(data, group_key="category", order_key="sales_amount")
        assert result[0]["product_name"] == "Y"


class TestShouldPostProcess:
    def test_trigger_conditions_met(self):
        from nl2dsl.dsl.models import DSL, OrderBy, Aggregation
        dsl = DSL(
            data_source="orders",
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["category", "product_name"],
            order_by=[OrderBy(field="sales_amount", direction="desc")],
            limit=1,
        )
        assert should_post_process(dsl) is True

    def test_no_trigger_single_dimension(self):
        from nl2dsl.dsl.models import DSL, OrderBy, Aggregation
        dsl = DSL(
            data_source="orders",
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["category"],
            order_by=[OrderBy(field="sales_amount", direction="desc")],
            limit=1,
        )
        assert should_post_process(dsl) is False


class TestAdvancedPostProcessing:
    def test_top_two_per_group(self):
        data = [
            {"category": "手机", "product": "A", "sales": 100},
            {"category": "手机", "product": "B", "sales": 80},
            {"category": "手机", "product": "C", "sales": 60},
            {"category": "电脑", "product": "D", "sales": 120},
            {"category": "电脑", "product": "E", "sales": 90},
        ]
        result = extract_top_n_per_group(
            data, ["category"], "sales", top_n=2, order_desc=True
        )
        assert [row["product"] for row in result] == ["A", "B", "D", "E"]

    def test_calculate_proportion(self):
        result = calculate_proportion(
            [{"category": "A", "sales": 30}, {"category": "B", "sales": 70}],
            "sales",
        )
        assert result[0]["sales_proportion"] == 0.3
        assert result[1]["sales_proportion"] == 0.7

    def test_zero_total_proportion(self):
        result = calculate_proportion(
            [{"category": "A", "sales": 0}, {"category": "B", "sales": 0}],
            "sales",
        )
        assert [row["sales_proportion"] for row in result] == [0.0, 0.0]

    def test_apply_group_top_n_spec(self):
        spec = PostProcess(
            type="group_top_n",
            metric="sales",
            group_by=["category"],
            top_n=1,
        )
        result = apply_post_process(
            [
                {"category": "A", "product": "x", "sales": 1},
                {"category": "A", "product": "y", "sales": 2},
            ],
            spec,
        )
        assert result == [{"category": "A", "product": "y", "sales": 2}]

    def test_no_trigger_limit_not_one(self):
        from nl2dsl.dsl.models import DSL, OrderBy, Aggregation
        dsl = DSL(
            data_source="orders",
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["category", "product_name"],
            order_by=[OrderBy(field="sales_amount", direction="desc")],
            limit=10,
        )
        assert should_post_process(dsl) is False

    def test_no_trigger_no_order_by(self):
        from nl2dsl.dsl.models import DSL, Aggregation
        dsl = DSL(
            data_source="orders",
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["category", "product_name"],
            limit=1,
        )
        assert should_post_process(dsl) is False
