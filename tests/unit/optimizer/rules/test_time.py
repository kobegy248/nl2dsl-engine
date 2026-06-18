"""Tests for T001-T003 Time rules."""

from datetime import date

import pytest
from nl2dsl.optimizer.context import SemanticConfig, RuleContext
from nl2dsl.optimizer.registry import RuleRegistry
from nl2dsl.optimizer.rules.time import (
    T001_InvalidTimeGrain,
    T002_MissingTimeContext,
    T003_MissingTimeRange,
)

REF = date(2026, 6, 18)


@pytest.fixture(autouse=True)
def clear_registry():
    RuleRegistry.clear()
    yield
    RuleRegistry.clear()


class TestT001InvalidTimeGrain:
    def test_triggers_when_grain_conflicts(self):
        ctx = RuleContext(semantic_config=SemanticConfig())
        rule = T001_InvalidTimeGrain()
        # "daily" maps to "day", "年" maps to "year" → conflict
        dsl = {"data_source": "orders", "metrics": [{"func": "sum", "field": "x", "alias": "daily_sales"}], "dimensions": ["年"]}
        result = rule.check(dsl, ctx)
        assert result.description != ""

    def test_does_not_trigger_without_grain_keywords(self):
        ctx = RuleContext(semantic_config=SemanticConfig())
        rule = T001_InvalidTimeGrain()
        dsl = {"data_source": "orders", "metrics": [{"func": "sum", "field": "x", "alias": "gmv"}]}
        result = rule.check(dsl, ctx)
        assert result.description == ""


class TestT002MissingTimeContext:
    def test_triggers_with_comparison_keyword(self):
        ctx = RuleContext(semantic_config=SemanticConfig(), original_question="GMV同比增长多少")
        rule = T002_MissingTimeContext()
        dsl = {"data_source": "orders"}
        result = rule.check(dsl, ctx)
        assert result.description != ""
        assert result.clarification_required is True

    def test_does_not_trigger_without_keyword(self):
        ctx = RuleContext(semantic_config=SemanticConfig(), original_question="GMV是多少")
        rule = T002_MissingTimeContext()
        dsl = {"data_source": "orders"}
        result = rule.check(dsl, ctx)
        assert result.description == ""


def _config_with_date_dim() -> SemanticConfig:
    return SemanticConfig(
        dimensions={"order_date": {"column": "order_date", "type": "date"}},
        data_sources={"orders": {"table": "order_fact", "dimensions": ["order_date"]}},
    )


class TestT003MissingTimeRange:
    def test_injects_resolvable_relative_time(self):
        ctx = RuleContext(
            semantic_config=_config_with_date_dim(),
            original_question="本月华东线上销售额",
            reference_date=REF,
        )
        rule = T003_MissingTimeRange()
        dsl = {"data_source": "orders"}
        result = rule.check(dsl, ctx)
        assert result.severity == "Fix"
        assert result.after["time_field"] == "order_date"
        assert result.after["time_range"] == ["2026-06-01", "2026-06-30"]

        fixed = rule.fix(dsl, result)
        assert fixed["time_field"] == "order_date"
        assert fixed["time_range"] == ("2026-06-01", "2026-06-30")

    def test_injects_recent_n_days(self):
        ctx = RuleContext(
            semantic_config=_config_with_date_dim(),
            original_question="最近7天销售额",
            reference_date=REF,
        )
        rule = T003_MissingTimeRange()
        dsl = {"data_source": "orders"}
        result = rule.check(dsl, ctx)
        assert result.severity == "Fix"
        assert result.after["time_range"] == ["2026-06-12", "2026-06-18"]

    def test_no_issue_when_time_range_already_set(self):
        ctx = RuleContext(
            semantic_config=_config_with_date_dim(),
            original_question="本月销售额",
            reference_date=REF,
        )
        rule = T003_MissingTimeRange()
        dsl = {"data_source": "orders", "time_range": ("2026-01-01", "2026-01-31")}
        result = rule.check(dsl, ctx)
        assert result.description == ""

    def test_no_issue_when_unresolvable(self):
        # "近期" is vague -> resolve_time returns None -> T003 yields to F003.
        ctx = RuleContext(
            semantic_config=_config_with_date_dim(),
            original_question="近期销售额",
            reference_date=REF,
        )
        rule = T003_MissingTimeRange()
        dsl = {"data_source": "orders"}
        result = rule.check(dsl, ctx)
        assert result.description == ""

    def test_no_issue_when_no_date_dimension(self):
        cfg = SemanticConfig(
            dimensions={"region": {"column": "region", "type": "string"}},
            data_sources={"orders": {"table": "order_fact", "dimensions": ["region"]}},
        )
        ctx = RuleContext(semantic_config=cfg, original_question="本月销售额", reference_date=REF)
        rule = T003_MissingTimeRange()
        dsl = {"data_source": "orders"}
        result = rule.check(dsl, ctx)
        assert result.description == ""
