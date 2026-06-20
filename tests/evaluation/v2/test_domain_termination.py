"""P0 integration: bank / supply_chain queries terminate in finite steps.

Previously every bank/supply_chain case hit GRAPH_RECURSION_LIMIT (~15s, 10007
iterations) because the rule generator invented ecommerce fields -> validation
failed -> the validate<->correct_dsl loop never terminated (correct_dsl in rule
mode appends no generation attempt, so generation_attempts stalled at 1).

These tests pin the fix: minimal queries finish well under the recursion budget,
produce no GRAPH_RECURSION_LIMIT, and the executor returns a finite observation.
"""

from __future__ import annotations

import pytest

from nl2dsl.evaluation.execution import ApiEvaluationExecutor
from nl2dsl.evaluation.v2_cli import build_default_executor_config


@pytest.fixture(scope="module")
def executor() -> ApiEvaluationExecutor:
    return ApiEvaluationExecutor(build_default_executor_config())


def _make_case(cid, domain, query):
    C = type("C", (), {})
    c = C()
    c.id = cid
    c.domain = domain
    c.query = query
    c.tags = []
    c.expected = {}
    return c


def _assert_no_recursion(obs):
    blob = (obs.error or "") + " ".join(str(s) for s in (obs.trace or []))
    assert "GRAPH_RECURSION_LIMIT" not in blob, (
        f"{obs.case_id}: hit recursion limit (error={obs.error!r})"
    )
    assert "Recursion limit of" not in blob, (
        f"{obs.case_id}: hit recursion limit (error={obs.error!r})"
    )


def test_bank_minimal_query_terminates(executor):
    """bank 最小查询在有限节点步数内结束（此前约 15s 撞 recursion limit）。

    终止信号是“不出现 GRAPH_RECURSION_LIMIT 且状态为 success/warning”；不再
    断言绝对延迟，因为 Milvus RAG auto-sync 在本机偶发 WinError 183 重试会
    叠加~15s 环境开销（与死循环无关，属于既有环境问题）。
    """
    obs = executor.execute(
        _make_case("bank_term", "bank", "查询客户数量"),
        generator_mode="rule", optimizer_enabled=False,
    )
    _assert_no_recursion(obs)
    # bank '查询客户数量' routes to bank registry and executes successfully.
    assert obs.status in ("success", "warning"), (
        f"bank query did not execute: status={obs.status} error={obs.error!r}"
    )


def test_supply_chain_minimal_query_terminates(executor):
    """supply_chain 最小查询在有限节点步数内结束。"""
    obs = executor.execute(
        _make_case("sc_term", "supply_chain", "总库存量"),
        generator_mode="rule", optimizer_enabled=False,
    )
    _assert_no_recursion(obs)
    assert obs.status in ("success", "warning"), (
        f"supply_chain query did not execute: status={obs.status} error={obs.error!r}"
    )


def test_bank_actual_dsl_uses_bank_registry(executor):
    """bank actual DSL 的 metric / dimension / data_source 均来自 bank registry。"""
    from pathlib import Path
    import yaml

    samples = Path(__file__).resolve().parents[3] / "nl2dsl" / "evaluation" / "samples"
    reg = yaml.safe_load((samples / "bank_metrics.yaml").read_text(encoding="utf-8"))
    bank_metrics = set(reg["metrics"])
    bank_dims = set(reg["dimensions"])
    bank_ds = set(reg["data_sources"])

    obs = executor.execute(
        _make_case("bank_dsl", "bank", "查询客户数量"),
        generator_mode="rule", optimizer_enabled=False,
    )
    dsl = obs.dsl_after_optimizer or {}
    assert dsl.get("data_source") in bank_ds
    for m in (dsl.get("metrics") or []):
        assert m.get("alias") in bank_metrics
    for d in (dsl.get("dimensions") or []):
        assert d in bank_dims


def test_supply_chain_actual_dsl_uses_supply_chain_registry(executor):
    """supply_chain actual DSL 的对应字段均来自 supply-chain registry。"""
    from pathlib import Path
    import yaml

    samples = Path(__file__).resolve().parents[3] / "nl2dsl" / "evaluation" / "samples"
    reg = yaml.safe_load(
        (samples / "supply_chain_metrics.yaml").read_text(encoding="utf-8")
    )
    sc_metrics = set(reg["metrics"])
    sc_dims = set(reg["dimensions"])
    sc_ds = set(reg["data_sources"])

    obs = executor.execute(
        _make_case("sc_dsl", "supply_chain", "总库存量"),
        generator_mode="rule", optimizer_enabled=False,
    )
    dsl = obs.dsl_after_optimizer or {}
    assert dsl.get("data_source") in sc_ds
    for m in (dsl.get("metrics") or []):
        assert m.get("alias") in sc_metrics
    for d in (dsl.get("dimensions") or []):
        assert d in sc_dims
