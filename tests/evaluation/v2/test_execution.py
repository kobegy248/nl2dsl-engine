"""Phase 0/1：真实评测执行器与矩阵测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from nl2dsl.evaluation.dataset import V2DatasetLoader
from nl2dsl.evaluation.execution import (
    ApiEvaluationExecutor,
    ExecutorConfig,
    FakeEvaluationExecutor,
    EvaluationObservation,
)
from nl2dsl.evaluation.v2_runner import V2BenchmarkRunner
from nl2dsl.evaluation.canonical.resolver import CanonicalResolver
from nl2dsl.evaluation.scorers.intent_scorer import IntentScorer
from nl2dsl.evaluation.scorers.metric_scorer import MetricScorer
from nl2dsl.evaluation.scorers.filter_scorer import FilterScorer
from nl2dsl.evaluation.scorers.planner_scorer import PlannerScorer
from nl2dsl.evaluation.scorers.governance_scorer import GovernanceScorer

FIXTURES = Path(__file__).resolve().parents[2] / "e2e" / "fixtures"
DATASET_V2 = Path(__file__).resolve().parents[2] / "evaluation" / "dataset" / "v2"


@pytest.fixture(scope="module")
def executor_config() -> ExecutorConfig:
    from tests.e2e.mock_data import create_mock_database

    engine, *_ = create_mock_database("sqlite:///:memory:")
    metrics = yaml.safe_load((FIXTURES / "metrics_test.yaml").read_text(encoding="utf-8"))
    perm = yaml.safe_load((FIXTURES / "permissions_test.yaml").read_text(encoding="utf-8"))
    registry = {
        "metrics": metrics.get("metrics", {}),
        "dimensions": metrics.get("dimensions", {}),
        "data_sources": metrics.get("data_sources", {}),
        "permissions": perm.get("users", {}),
    }
    return ExecutorConfig(
        engine=engine,
        registry_dict=registry,
        permissions=perm.get("users", {}),
        sensitive_columns=perm.get("sensitive_columns", {}),
        masking_rules=perm.get("masking_rules", {}),
        llm_client=None,
    )


@pytest.fixture(scope="module")
def resolver(executor_config) -> CanonicalResolver:
    return CanonicalResolver.from_config(executor_config.registry_dict)


def _runner(executor_config) -> V2BenchmarkRunner:
    executor = ApiEvaluationExecutor(executor_config)
    return V2BenchmarkRunner(
        {
            "intent_scorer": IntentScorer(),
            "metric_scorer": MetricScorer(CanonicalResolver.from_config(executor_config.registry_dict).metric),
            "filter_scorer": FilterScorer(CanonicalResolver.from_config(executor_config.registry_dict)),
            "planner_scorer": PlannerScorer(CanonicalResolver.from_config(executor_config.registry_dict)),
            "governance_scorer": GovernanceScorer(),
        },
        injected_filters=executor.injected_filters,
    )


def _load_cases():
    return V2DatasetLoader(DATASET_V2).load_all()


# --- P0: expected 改变不会影响 actual DSL ---

def test_expected_change_does_not_affect_actual_dsl(executor_config, resolver):
    """改动 expected 不应改变 actual DSL（actual 来自真实链路）。"""
    cases = _load_cases()
    case = next(c for c in cases if c.id == "BASIC_001")

    executor = ApiEvaluationExecutor(executor_config)
    obs1 = executor.execute(case, generator_mode="rule", optimizer_enabled=False)

    # 篡改 expected（模拟"从 expected 构造 actual"的反例）
    case.expected = {"intent": "rank", "metric": "order_count", "filters": [{"field": "x", "operator": "=", "value": 1}]}
    obs2 = executor.execute(case, generator_mode="rule", optimizer_enabled=False)

    assert obs1.dsl_after_optimizer == obs2.dsl_after_optimizer
    assert obs1.status == obs2.status


# --- P1: Optimizer OFF 的 Trace 不含 optimize_dsl ---

def test_optimizer_off_trace_has_no_optimize_node(executor_config):
    cases = _load_cases()
    case = next(c for c in cases if c.id == "BASIC_001")
    executor = ApiEvaluationExecutor(executor_config)
    obs = executor.execute(case, generator_mode="rule", optimizer_enabled=False)
    steps = {s.get("step") for s in (obs.trace or []) if isinstance(s, dict)}
    assert "optimize_dsl" not in steps
    assert obs.optimizer_enabled is False


def test_optimizer_on_trace_has_optimize_node(executor_config):
    cases = _load_cases()
    case = next(c for c in cases if c.id == "BASIC_001")
    executor = ApiEvaluationExecutor(executor_config)
    obs = executor.execute(case, generator_mode="rule", optimizer_enabled=True)
    steps = {s.get("step") for s in (obs.trace or []) if isinstance(s, dict)}
    assert "optimize_dsl" in steps
    assert obs.optimizer_enabled is True


# --- P1: LLM 不可用时返回 unavailable ---

def test_llm_unavailable_returns_unavailable(executor_config):
    cases = _load_cases()
    case = cases[0]
    # executor_config.llm_client is None → llm 模式必须 unavailable
    executor = ApiEvaluationExecutor(executor_config)
    obs = executor.execute(case, generator_mode="llm", optimizer_enabled=False)
    assert obs.status == "unavailable"
    assert obs.error is not None


def test_unavailable_does_not_pass(executor_config, resolver):
    cases = _load_cases()
    case = cases[0]
    executor = ApiEvaluationExecutor(executor_config)
    runner = _runner(executor_config)
    obs = executor.execute(case, generator_mode="llm", optimizer_enabled=False)
    result = runner.score_observation(case, obs, resolver)
    assert result["passed"] is False
    assert result["status"] == "unavailable"


# --- P1: domain / tags 过滤 ---

def test_domain_and_tags_filter():
    from nl2dsl.evaluation.v2_cli import _filter_cases

    cases = _load_cases()
    # v2 是数据集版本目录，不是业务 domain；用例必须解析为真实业务 domain（ecommerce）。
    domains = {c.domain for c in cases}
    assert "v2" not in domains
    assert "ecommerce" in domains

    filtered = _filter_cases(cases, domain="ecommerce", tags=None)
    assert len(filtered) == len(cases)

    tagged = _filter_cases(cases, domain=None, tags=["ranking"])
    assert all("ranking" in (c.tags or []) for c in tagged)
    assert len(tagged) > 0

    none = _filter_cases(cases, domain="nonexistent", tags=None)
    assert none == []


# --- P0: FakeEvaluationExecutor ---

def test_fake_executor():
    case = type("C", (), {"id": "X1", "domain": "ecommerce", "query": "q"})()
    obs = EvaluationObservation(
        case_id="X1", domain="ecommerce", generator_mode="rule",
        optimizer_enabled=False, status="success", dsl_after_optimizer={"data_source": "orders"},
    )
    fake = FakeEvaluationExecutor({"X1": obs})
    out = fake.execute(case, generator_mode="rule", optimizer_enabled=False)
    assert out is obs


# --- P1-6: 多领域评测按 case.domain 路由到真实 DomainContext ---

def _make_case(cid, domain, query="查询华东地区的销售额"):
    C = type("C", (), {})
    c = C()
    c.id = cid
    c.domain = domain
    c.query = query
    c.tags = []
    c.expected = {}
    return c


def test_multi_domain_routes_to_distinct_registries():
    """相同自然语言在不同 domain 下使用各自语义注册表，不共享错误注册表。"""
    import copy
    from tests.e2e.mock_data import create_mock_database
    from nl2dsl.evaluation.execution import DomainAppConfig

    engine, *_ = create_mock_database("sqlite:///:memory:")
    metrics = yaml.safe_load((FIXTURES / "metrics_test.yaml").read_text(encoding="utf-8"))
    perm = yaml.safe_load((FIXTURES / "permissions_test.yaml").read_text(encoding="utf-8"))

    alpha_registry = {
        "metrics": metrics.get("metrics", {}),
        "dimensions": metrics.get("dimensions", {}),
        "data_sources": metrics.get("data_sources", {}),
        "permissions": perm.get("users", {}),
    }
    # beta：与 alpha 相同的表结构，但 region 的 value_map 改为不同编码，
    # 用于证明不同 domain 使用各自注册表。
    beta_registry = copy.deepcopy(alpha_registry)
    beta_registry["dimensions"]["region"]["value_map"]["华东"] = "BETA_HD"

    config = ExecutorConfig(
        llm_client=None,
        domains={
            "alpha": DomainAppConfig(
                domain="alpha", engine=engine, registry_dict=alpha_registry,
                permissions=perm.get("users", {}),
                sensitive_columns=perm.get("sensitive_columns", {}),
                masking_rules=perm.get("masking_rules", {}),
            ),
            "beta": DomainAppConfig(
                domain="beta", engine=engine, registry_dict=beta_registry,
                permissions=perm.get("users", {}),
                sensitive_columns=perm.get("sensitive_columns", {}),
                masking_rules=perm.get("masking_rules", {}),
            ),
        },
    )
    executor = ApiEvaluationExecutor(config)

    obs_alpha = executor.execute(_make_case("A1", "alpha"), generator_mode="rule", optimizer_enabled=False)
    obs_beta = executor.execute(_make_case("B1", "beta"), generator_mode="rule", optimizer_enabled=False)

    assert obs_alpha.domain == "alpha"
    assert obs_beta.domain == "beta"

    def _region_value(dsl):
        for f in (dsl or {}).get("filters", []) or []:
            if f.get("field") in ("region", "region_code"):
                return f.get("value")
        return None

    # alpha 用 alpha 注册表 → HD；beta 用 beta 注册表 → BETA_HD
    assert _region_value(obs_alpha.dsl_after_optimizer) == "HD"
    assert _region_value(obs_beta.dsl_after_optimizer) == "BETA_HD"


def test_unknown_domain_returns_error():
    """未知 domain 必须明确失败，不静默回退 ecommerce。"""
    from tests.e2e.mock_data import create_mock_database
    engine, *_ = create_mock_database("sqlite:///:memory:")
    metrics = yaml.safe_load((FIXTURES / "metrics_test.yaml").read_text(encoding="utf-8"))
    perm = yaml.safe_load((FIXTURES / "permissions_test.yaml").read_text(encoding="utf-8"))
    registry = {
        "metrics": metrics.get("metrics", {}),
        "dimensions": metrics.get("dimensions", {}),
        "data_sources": metrics.get("data_sources", {}),
        "permissions": perm.get("users", {}),
    }
    config = ExecutorConfig(
        engine=engine, registry_dict=registry,
        permissions=perm.get("users", {}),
        sensitive_columns=perm.get("sensitive_columns", {}),
        masking_rules=perm.get("masking_rules", {}),
        llm_client=None, default_domain="ecommerce",
    )
    executor = ApiEvaluationExecutor(config)
    obs = executor.execute(_make_case("U1", "bank"), generator_mode="rule", optimizer_enabled=False)
    assert obs.status == "error"
    assert "bank" in (obs.error or "")


def test_dataset_version_dir_not_a_domain():
    """数据集版本目录名（v2）不会被解析为业务 domain。"""
    cases = _load_cases()
    domains = {c.domain for c in cases}
    assert "v2" not in domains
    # v2 用例全部归属真实业务 domain
    assert domains.issubset({"ecommerce", "bank", "supply_chain"})


# --- 第二轮审阅 P1：默认 V2 CLI 真正支持多领域 ---

def test_default_executor_config_has_three_domains():
    """默认 ExecutorConfig 同时包含 ecommerce / bank / supply_chain 三个领域。"""
    from nl2dsl.evaluation.v2_cli import build_default_executor_config

    config = build_default_executor_config()
    assert config.domains is not None
    assert set(config.domains.keys()) == {"ecommerce", "bank", "supply_chain"}


def test_default_config_each_domain_uses_own_registry():
    """每个领域使用各自的语义注册表，指标名互不串用。"""
    from nl2dsl.evaluation.v2_cli import build_default_executor_config

    config = build_default_executor_config()
    eco = config.get_domain_config("ecommerce").registry_dict
    bank = config.get_domain_config("bank").registry_dict
    sc = config.get_domain_config("supply_chain").registry_dict

    # ecommerce 注册了 sales_amount
    assert "sales_amount" in eco["metrics"]
    # bank 注册表不含 ecommerce 的 sales_amount（不串用）
    assert "sales_amount" not in bank["metrics"]
    # bank 有自己的指标
    assert len(bank["metrics"]) > 0
    # supply_chain 有自己的指标，且与 ecommerce 不同
    assert len(sc["metrics"]) > 0
    assert sc["metrics"] != eco["metrics"]


def test_default_config_each_domain_has_independent_engine_and_identity():
    """每个领域独立 engine / 权限 / 评测身份。"""
    from nl2dsl.evaluation.v2_cli import build_default_executor_config

    config = build_default_executor_config()
    eco = config.get_domain_config("ecommerce")
    bank = config.get_domain_config("bank")
    sc = config.get_domain_config("supply_chain")
    # 独立 engine
    assert eco.engine is not None and bank.engine is not None and sc.engine is not None
    assert eco.engine is not bank.engine
    # 各自评测身份
    assert eco.eval_user_id == "u001"
    assert bank.eval_user_id == "b001"
    assert sc.eval_user_id == "sc001"
    # 权限各自独立
    assert "u001" in eco.permissions
    assert "b001" in bank.permissions
    assert "sc001" in sc.permissions


def test_default_config_injected_filters_per_domain():
    """治理注入过滤条件按领域各自的评测身份生成。"""
    from nl2dsl.evaluation.v2_cli import build_default_executor_config

    config = build_default_executor_config()
    eco_filters = config.injected_filters_for("ecommerce")
    bank_filters = config.injected_filters_for("bank")
    sc_filters = config.injected_filters_for("supply_chain")
    # 都注入了 tenant_id
    assert any(f["field"] == "tenant_id" for f in eco_filters)
    assert any(f["field"] == "tenant_id" for f in bank_filters)
    assert any(f["field"] == "tenant_id" for f in sc_filters)
    # 行级权限字段按领域不同（ecommerce=region, bank=org_name, supply_chain=region_code）
    eco_fields = {f["field"] for f in eco_filters}
    bank_fields = {f["field"] for f in bank_filters}
    assert "region" in eco_fields
    assert "org_name" in bank_fields


def test_default_config_unknown_domain_returns_none():
    """未知领域 get_domain_config 返回 None（执行器据此返回 error，不静默回退）。"""
    from nl2dsl.evaluation.v2_cli import build_default_executor_config

    config = build_default_executor_config()
    assert config.get_domain_config("nonexistent") is None


def test_default_config_executes_bank_case_against_bank_registry():
    """bank 用例经默认多领域执行器路由到 bank 领域（不报“未配置领域”错误）。"""
    from nl2dsl.evaluation.v2_cli import build_default_executor_config

    config = build_default_executor_config()
    executor = ApiEvaluationExecutor(config)
    case = _make_case("bank_x", "bank", query="查询客户数量")
    obs = executor.execute(case, generator_mode="rule", optimizer_enabled=False)
    # 路由到 bank 领域（不是 “未配置的业务领域” 错误）
    assert obs.domain == "bank"
    assert obs.status != "error" or "未配置的业务领域" not in (obs.error or "")
