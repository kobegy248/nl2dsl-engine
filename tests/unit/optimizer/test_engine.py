"""Tests for RuleEngine."""

import pytest
from nl2dsl.optimizer.base import BaseRule, RuleResult
from nl2dsl.optimizer.context import SemanticConfig, RuleContext
from nl2dsl.optimizer.engine import RuleEngine
from nl2dsl.optimizer.metadata import RuleMetadata
from nl2dsl.optimizer.registry import RuleRegistry


@pytest.fixture(autouse=True)
def clear_registry():
    RuleRegistry.clear()
    yield
    RuleRegistry.clear()


@pytest.fixture
def context():
    return RuleContext(semantic_config=SemanticConfig())


class TestRuleEngineFatalReject:
    def test_fatal_reject_stops_pipeline(self, context):
        @RuleRegistry.register
        class FatalRule(BaseRule):
            metadata = RuleMetadata(
                error_code="S001",
                category="Structural",
                description="Always fatal",
                priority=1,
                severity="Reject",
                confidence="high",
                is_fatal=True,
            )

            def check(self, dsl, ctx):
                return RuleResult.from_metadata(
                    self.metadata,
                    description="Fatal error",
                )

        @RuleRegistry.register
        class ShouldNotRun(BaseRule):
            metadata = RuleMetadata(
                error_code="M001",
                category="Metric",
                description="Should not run",
                priority=2,
                severity="Fix",
                confidence="high",
                auto_fixable=True,
            )

            def check(self, dsl, ctx):
                return RuleResult.from_metadata(
                    self.metadata,
                    description="I should not have been called",
                )

        engine = RuleEngine(context)
        dsl, report = engine.run({"data_source": "orders"})
        assert report.fatal is True
        assert report.total_rules_triggered == 1
        assert report.fatal_rejection["error_code"] == "S001"

    def test_normal_reject_does_not_stop(self, context):
        @RuleRegistry.register
        class NormalRejectRule(BaseRule):
            metadata = RuleMetadata(
                error_code="M004",
                category="Metric",
                description="Normal reject",
                priority=3,
                severity="Reject",
                confidence="high",
                is_fatal=False,
            )

            def check(self, dsl, ctx):
                return RuleResult.from_metadata(
                    self.metadata,
                    description="Normal rejection",
                )

        @RuleRegistry.register
        class LaterRule(BaseRule):
            metadata = RuleMetadata(
                error_code="M002",
                category="Metric",
                description="Should still run",
                priority=5,
                severity="Warn",
                confidence="low",
            )

            def check(self, dsl, ctx):
                return RuleResult.from_metadata(
                    self.metadata,
                    description="Warning from later rule",
                )

        engine = RuleEngine(context)
        dsl, report = engine.run({"data_source": "orders"})
        assert report.fatal is False
        assert report.total_rules_triggered == 2
        assert len(report.rejections) == 1
        assert len(report.warnings_issued) == 1


class TestRuleEngineFixes:
    def test_fix_is_applied_and_dsl_updated(self, context):
        @RuleRegistry.register
        class FixRule(BaseRule):
            metadata = RuleMetadata(
                error_code="M003",
                category="Metric",
                description="Add missing alias",
                priority=2,
                severity="Fix",
                confidence="high",
                auto_fixable=True,
            )

            def check(self, dsl, ctx):
                metrics = dsl.get("metrics", [])
                for i, m in enumerate(metrics):
                    if not m.get("alias"):
                        return RuleResult.from_metadata(
                            self.metadata,
                            description="Missing alias",
                            before={"alias": None},
                            after={"alias": "fixed_alias"},
                            location=f"metrics[{i}].alias",
                        )
                return RuleResult.no_issue("M003", "Metric")

        engine = RuleEngine(context)
        dsl, report = engine.run(
            {
                "data_source": "orders",
                "metrics": [{"func": "sum", "field": "amount"}],
            }
        )
        assert report.total_rules_triggered == 1
        assert len(report.fixes_applied) == 1
        assert dsl["metrics"][0]["alias"] == "fixed_alias"


class TestRuleEngineWhitelistBlacklist:
    def test_enabled_rules_whitelist(self, context):
        @RuleRegistry.register
        class RuleA(BaseRule):
            metadata = RuleMetadata(
                error_code="M001", category="Metric", description="A",
                priority=2, severity="Fix", confidence="high", auto_fixable=True,
            )
            def check(self, dsl, ctx):
                return RuleResult.from_metadata(self.metadata, description="A triggered")

        @RuleRegistry.register
        class RuleB(BaseRule):
            metadata = RuleMetadata(
                error_code="M002", category="Metric", description="B",
                priority=5, severity="Warn", confidence="low",
            )
            def check(self, dsl, ctx):
                return RuleResult.from_metadata(self.metadata, description="B triggered")

        engine = RuleEngine(context)
        dsl, report = engine.run(
            {"data_source": "orders"}, enabled_rules=["M001"]
        )
        assert report.total_rules_triggered == 1
        assert report.fixes_applied[0]["error_code"] == "M001"

    def test_disabled_rules_blacklist(self, context):
        @RuleRegistry.register
        class RuleA(BaseRule):
            metadata = RuleMetadata(
                error_code="M001", category="Metric", description="A",
                priority=2, severity="Fix", confidence="high", auto_fixable=True,
            )
            def check(self, dsl, ctx):
                return RuleResult.from_metadata(self.metadata, description="A triggered")

        @RuleRegistry.register
        class RuleB(BaseRule):
            metadata = RuleMetadata(
                error_code="M002", category="Metric", description="B",
                priority=5, severity="Warn", confidence="low",
            )
            def check(self, dsl, ctx):
                return RuleResult.from_metadata(self.metadata, description="B triggered")

        engine = RuleEngine(context)
        dsl, report = engine.run(
            {"data_source": "orders"}, disabled_rules=["M001"]
        )
        assert report.total_rules_triggered == 1
        assert report.warnings_issued[0]["error_code"] == "M002"


class TestRuleEngineErrorHandling:
    def test_rule_exception_produces_warning(self, context):
        @RuleRegistry.register
        class CrashRule(BaseRule):
            metadata = RuleMetadata(
                error_code="M999",
                category="Metric",
                description="Will crash",
                priority=2,
                severity="Fix",
                confidence="high",
            )
            def check(self, dsl, ctx):
                raise RuntimeError("Boom!")

        engine = RuleEngine(context)
        dsl, report = engine.run({"data_source": "orders"})
        assert report.total_rules_triggered == 1
        assert len(report.warnings_issued) == 1
        assert "Boom" in report.warnings_issued[0]["description"]
