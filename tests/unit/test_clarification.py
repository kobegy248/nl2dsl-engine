import pytest
from nl2dsl.query.clarification import ClarificationDetector


class TestClarificationDetector:
    @pytest.fixture
    def detector(self):
        return ClarificationDetector()

    def test_time_missing(self, detector):
        items = detector.detect("查询销售额")
        assert any(i.type == "time_missing" for i in items)

    def test_time_present_month(self, detector):
        items = detector.detect("查询本月销售额")
        assert not any(i.type == "time_missing" for i in items)

    def test_time_present_year(self, detector):
        items = detector.detect("查询2024年销售额")
        assert not any(i.type == "time_missing" for i in items)

    def test_time_present_date_pattern(self, detector):
        items = detector.detect("查询2024年5月销售额")
        assert not any(i.type == "time_missing" for i in items)

    def test_time_present_recent(self, detector):
        items = detector.detect("查询最近7天的销售额")
        assert not any(i.type == "time_missing" for i in items)

    def test_metric_ambiguous_sales(self, detector):
        items = detector.detect("销量怎么样")
        assert any(i.type == "metric_ambiguous" and "销量" in i.question for i in items)

    def test_metric_ambiguous_sales_amount(self, detector):
        items = detector.detect("销售额是多少")
        assert any(i.type == "metric_ambiguous" and "销售额" in i.question for i in items)

    def test_metric_ambiguous_customer(self, detector):
        items = detector.detect("客户数有多少")
        assert any(i.type == "metric_ambiguous" and "客户数" in i.question for i in items)

    def test_dimension_ambiguous_region(self, detector):
        items = detector.detect("按地区统计")
        assert any(i.type == "dimension_ambiguous" and "地区" in i.question for i in items)

    def test_dimension_ambiguous_time(self, detector):
        items = detector.detect("按时间统计")
        assert any(i.type == "dimension_ambiguous" and "时间" in i.question for i in items)

    def test_comparison_ambiguous_growth(self, detector):
        items = detector.detect("销售额增长了多少")
        assert any(i.type == "comparison_ambiguous" for i in items)

    def test_comparison_ambiguous_decline(self, detector):
        items = detector.detect("销量下降了")
        assert any(i.type == "comparison_ambiguous" for i in items)

    def test_comparison_not_ambiguous_with_base(self, detector):
        items = detector.detect("销售额同比增长")
        assert not any(i.type == "comparison_ambiguous" for i in items)

    def test_comparison_not_ambiguous_with_last_month(self, detector):
        items = detector.detect("销售额环比上月")
        assert not any(i.type == "comparison_ambiguous" for i in items)

    def test_no_ambiguity_clear_question(self, detector):
        items = detector.detect("查询本月的订单")
        # 有时间、无歧义指标、无歧义维度、无比较
        assert not any(i.type == "time_missing" for i in items)
        assert not any(i.type == "metric_ambiguous" for i in items)
        assert not any(i.type == "dimension_ambiguous" for i in items)
        assert not any(i.type == "comparison_ambiguous" for i in items)

    def test_multiple_ambiguities(self, detector):
        items = detector.detect("销量增长了多少")
        # 缺时间 + 指标歧义（销量） + 比较歧义
        assert any(i.type == "time_missing" for i in items)
        assert any(i.type == "metric_ambiguous" for i in items)
        assert any(i.type == "comparison_ambiguous" for i in items)

    def test_options_populated(self, detector):
        items = detector.detect("查询销售额")
        time_item = next(i for i in items if i.type == "time_missing")
        assert len(time_item.options) > 0
        assert "本月" in time_item.options

    def test_case_insensitive(self, detector):
        items = detector.detect("查询本月SALES")
        assert not any(i.type == "time_missing" for i in items)
