"""P1: V2 CLI exit codes distinguish infrastructure failures from low scores.

The CLI previously returned 0 even when every case was status=error with
GRAPH_RECURSION_LIMIT. It must now return non-zero for infrastructure failures
(recursion, all-error, no scoreable results), while normal scoreable runs
(possibly low-scored) still return 0. Baseline regression behavior is preserved.

These tests stub the executor (no LLM / no Milvus) by monkeypatching
``ApiEvaluationExecutor`` and ``build_default_executor_config`` in the CLI
module, so they run in milliseconds.
"""

from __future__ import annotations

import json
from pathlib import Path

from nl2dsl.evaluation import v2_cli
from nl2dsl.evaluation.execution import (
    EvaluationObservation,
    ExecutorConfig,
)


DATASET = Path(__file__).resolve().parents[2] / "evaluation" / "dataset"


class _StubExecutor:
    """Minimal executor: returns a fixed observation per case.id, plus the
    injected_filters attribute the runner reads."""

    def __init__(self, mapping):
        self._mapping = mapping
        self.injected_filters = []

    def execute(self, case, *, generator_mode, optimizer_enabled):
        obs = self._mapping.get(case.id)
        if obs is None:
            return EvaluationObservation(
                case_id=case.id, domain=getattr(case, "domain", "ecommerce"),
                generator_mode=generator_mode, optimizer_enabled=optimizer_enabled,
                status="error", error="no stub observation",
            )
        return obs


class _StubExecutorFactory:
    """Patches ``ApiEvaluationExecutor(config)`` -> a fixed stub executor."""

    def __init__(self, mapping):
        self._mapping = mapping
        self.last = None

    def __call__(self, config):
        self.last = _StubExecutor(self._mapping)
        return self.last


def _patch(monkeypatch, mapping):
    config = ExecutorConfig(llm_client=None, default_domain="ecommerce")
    monkeypatch.setattr(v2_cli, "build_default_executor_config", lambda *a, **k: config)
    monkeypatch.setattr(v2_cli, "ApiEvaluationExecutor", _StubExecutorFactory(mapping))


def _run(monkeypatch, mapping, tmp_path, extra=()):
    _patch(monkeypatch, mapping)
    argv = ["--dataset", str(DATASET), "--generator", "rule", "--optimizer", "off",
            "--output", str(tmp_path / "out")]
    argv.extend(extra)
    return v2_cli.main(argv)


# ---------------------------------------------------------------------------
# Recursion error -> non-zero
# ---------------------------------------------------------------------------


def _err_obs(cid, err):
    return EvaluationObservation(
        case_id=cid, domain="ecommerce", generator_mode="rule",
        optimizer_enabled=False, status="error", error=err,
    )


def _ok_obs(cid, dsl=None):
    return EvaluationObservation(
        case_id=cid, domain="ecommerce", generator_mode="rule",
        optimizer_enabled=False, status="success",
        dsl_after_optimizer=dsl or {"data_source": "orders"},
    )


def _all_case_ids():
    from nl2dsl.evaluation.dataset import V2DatasetLoader
    return [c.id for c in V2DatasetLoader(DATASET).load_all()]


def test_recursion_limit_returns_nonzero(monkeypatch, tmp_path):
    ids = _all_case_ids()
    mapping = {ids[0]: _err_obs(ids[0], "Recursion limit of 10007 reached without hitting a stop condition. GRAPH_RECURSION_LIMIT")}
    for cid in ids[1:]:
        mapping[cid] = _ok_obs(cid)
    code = _run(monkeypatch, mapping, tmp_path)
    assert code != 0


def test_all_execution_errors_return_nonzero(monkeypatch, tmp_path):
    """All cases status=error (no recursion marker) -> non-zero."""
    ids = _all_case_ids()
    mapping = {cid: _err_obs(cid, "Query execution failed") for cid in ids}
    code = _run(monkeypatch, mapping, tmp_path)
    assert code != 0


def test_normal_scoreable_run_returns_zero(monkeypatch, tmp_path):
    """A run with scoreable results returns 0 even if some score low."""
    ids = _all_case_ids()
    mapping = {cid: _ok_obs(cid) for cid in ids}
    code = _run(monkeypatch, mapping, tmp_path)
    assert code == 0


def test_mixed_success_and_error_not_all_error_returns_zero(monkeypatch, tmp_path):
    """Some scoreable successes + some errors (not all error) -> 0 (default)."""
    ids = _all_case_ids()
    mapping = {cid: _ok_obs(cid) for cid in ids[:-1]}
    mapping[ids[-1]] = _err_obs(ids[-1], "boom")
    code = _run(monkeypatch, mapping, tmp_path)
    assert code == 0


def test_fail_on_execution_error_flag_returns_nonzero(monkeypatch, tmp_path):
    """--fail-on-execution-error: any single execution error -> non-zero."""
    ids = _all_case_ids()
    mapping = {cid: _ok_obs(cid) for cid in ids[:-1]}
    mapping[ids[-1]] = _err_obs(ids[-1], "boom")
    code = _run(monkeypatch, mapping, tmp_path, extra=["--fail-on-execution-error"])
    assert code != 0


def test_report_summary_has_execution_errors_field(monkeypatch, tmp_path):
    ids = _all_case_ids()
    mapping = {cid: _ok_obs(cid) for cid in ids[:-1]}
    mapping[ids[-1]] = _err_obs(ids[-1], "boom")
    code = _run(monkeypatch, mapping, tmp_path)
    assert code == 0
    report = json.loads((tmp_path / "out" / "benchmark_report.json").read_text(encoding="utf-8"))
    assert report["summary"]["execution_errors"] == 1
