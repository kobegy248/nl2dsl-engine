"""Baseline 保存、读取与回归门禁。

Phase 2：将一次评测的结构化报告沉淀为带 ``schema_version`` 的 Baseline JSON，
供后续运行做回归对比。门禁默认保守：

- Overall 不得下降。
- 任一评分维度下降超过阈值（默认 2 个百分点）则失败。
- 单用例分数下降超过阈值（默认 10 个百分点）则失败。
- 新增失败用例则失败。
- ``unavailable`` 不算通过。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from nl2dsl.utils.logger import get_logger

logger = get_logger("evaluation.baseline")

BASELINE_SCHEMA_VERSION = "1.0"
# 受支持的 Baseline schema 版本集合；不在集合内的 schema_version 一律判为不兼容。
SUPPORTED_SCHEMAS = {BASELINE_SCHEMA_VERSION}


def _git_commit() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        )
        return out.decode().strip()
    except Exception:
        return "unknown"


def _case_normalizable(c) -> dict:
    """提取参与 dataset hash 的规范字段（影响评测语义的全部字段）。"""
    def _get(name, default=""):
        if isinstance(c, dict):
            return c.get(name, default)
        return getattr(c, name, default)
    return {
        "id": _get("id"),
        "domain": _get("domain"),
        "query": _get("query"),
        "expected": _get("expected", {}) or {},
        "tags": list(_get("tags", []) or []),
        "category": _get("category", ""),
        "difficulty": _get("difficulty", ""),
    }


def compute_dataset_hash(cases: list[Any]) -> str:
    """对用例集合计算稳定哈希。

    覆盖影响评测语义的全部字段：id / domain / query / expected / tags /
    category / difficulty。修改 expected、domain 或 tags 都会改变 hash；
    字典键顺序变化不会改变 hash（``sort_keys=True`` + 列表按 id 排序）。
    """
    normalized = [_case_normalizable(c) for c in cases]
    # 按 id 排序，消除用例顺序影响；json.dumps sort_keys 消除键顺序影响。
    normalized.sort(key=lambda d: str(d.get("id", "")))
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _matrix_combos_from_report(report: dict) -> list[dict]:
    """从报告的 by_matrix 提取稳定的矩阵组合列表。"""
    combos: list[dict] = []
    for m in report.get("by_matrix", []) or []:
        combos.append({
            "generator": m.get("generator"),
            "optimizer": m.get("optimizer"),
        })
    combos.sort(key=lambda d: (str(d.get("generator") or ""), str(d.get("optimizer") or "")))
    return combos


def save_baseline(
    report: dict,
    cases: list[Any],
    path: Path | str,
    *,
    matrix: dict | None = None,
) -> Path:
    """将结构化报告保存为 Baseline JSON。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    dataset_hash = report.get("dataset_hash") or compute_dataset_hash(cases)
    baseline = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(),
        "git_commit": _git_commit(),
        "dataset_hash": dataset_hash,
        "matrix": matrix or {},
        "matrix_combos": _matrix_combos_from_report(report),
        "summary": report.get("summary", {}),
        "by_dimension": report.get("summary", {}).get("by_dimension", {}),
        "cases": report.get("cases", {}),
    }
    path.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    logger.info("Baseline 已保存至 %s", path)
    return path


def load_baseline(path: Path | str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _current_matrix_combos(current: dict) -> list[dict] | None:
    """当前报告的矩阵组合：优先用显式 matrix_combos，否则从 by_matrix 派生。

    返回 ``None`` 表示当前报告完全没有矩阵身份信息（既无 matrix_combos 也无
    by_matrix），调用方据此判定身份缺失。
    """
    cur = current.get("matrix_combos")
    if cur is not None:
        return cur
    if current.get("by_matrix"):
        return _matrix_combos_from_report(current)
    return None


def evaluate_regression(
    current: dict,
    baseline: dict,
    *,
    max_dimension_drop: float = 0.02,
    max_case_drop: float = 0.10,
) -> dict:
    """对比当前报告与 baseline，返回回归详情与门禁结论。

    身份校验 fail-closed：在比较分数前先校验 schema_version / dataset_hash /
    matrix_combos 三类身份字段。Baseline 或当前报告任一必需身份字段缺失、为空、
    格式错误或 schema 不受支持，门禁立即失败并给出“Baseline 不兼容或损坏”原因，
    **不得**默认按零分继续比较后放行。``matrix_combos=[]``（空列表）与字段缺失
    严格区分：空列表是合法的“无矩阵”身份，缺失则是损坏。
    """
    compatibility: list[dict] = []
    reasons: list[str] = []

    # --- schema_version：双方必须有非空值；baseline 必须是受支持版本 ---
    base_schema = baseline.get("schema_version")
    cur_schema = current.get("schema_version")
    if not base_schema:
        compatibility.append({"check": "schema_version", "missing": "baseline"})
        reasons.append("Baseline 不兼容或损坏：缺少 schema_version")
    elif base_schema not in SUPPORTED_SCHEMAS:
        compatibility.append({
            "check": "schema_version",
            "baseline": base_schema,
            "supported": sorted(SUPPORTED_SCHEMAS),
        })
        reasons.append(
            f"Baseline 不兼容或损坏：不支持的 schema_version={base_schema}"
            f"（受支持：{sorted(SUPPORTED_SCHEMAS)}），请重新建立 Baseline（--save-baseline）"
        )
    if not cur_schema:
        compatibility.append({"check": "schema_version", "missing": "current"})
        reasons.append("当前报告缺少 schema_version，无法做身份校验")
    elif base_schema and base_schema in SUPPORTED_SCHEMAS and base_schema != cur_schema:
        compatibility.append({"check": "schema_version", "baseline": base_schema, "current": cur_schema})
        reasons.append(f"schema_version 不一致：baseline={base_schema} current={cur_schema}")

    # --- dataset_hash：双方必须有非空值，且一致 ---
    base_hash = baseline.get("dataset_hash")
    cur_hash = current.get("dataset_hash")
    if not base_hash:
        compatibility.append({"check": "dataset_hash", "missing": "baseline"})
        reasons.append("Baseline 不兼容或损坏：缺少 dataset_hash")
    if not cur_hash:
        compatibility.append({"check": "dataset_hash", "missing": "current"})
        reasons.append("当前报告缺少 dataset_hash，无法做身份校验")
    if base_hash and cur_hash and base_hash != cur_hash:
        compatibility.append({"check": "dataset_hash", "baseline": base_hash, "current": cur_hash})
        reasons.append(
            "dataset_hash 不一致：评测用例集合已改变（expected/domain/tags 等），"
            "请重新建立 Baseline（--save-baseline）"
        )

    # --- matrix_combos：baseline 必须有该字段且为列表（[] 合法）；current 需有矩阵身份 ---
    base_combos = baseline.get("matrix_combos")
    if base_combos is None:
        compatibility.append({"check": "matrix_combos", "missing": "baseline"})
        reasons.append("Baseline 不兼容或损坏：缺少 matrix_combos（空列表 [] 合法，字段缺失即损坏）")
    elif not isinstance(base_combos, list):
        compatibility.append({"check": "matrix_combos", "baseline_type": type(base_combos).__name__})
        reasons.append("Baseline 不兼容或损坏：matrix_combos 格式错误（应为列表）")

    cur_combos = _current_matrix_combos(current)
    if cur_combos is None:
        compatibility.append({"check": "matrix_combos", "missing": "current"})
        reasons.append("当前报告缺少矩阵组合（matrix_combos / by_matrix），无法做身份校验")
    elif isinstance(base_combos, list) and base_combos != cur_combos:
        compatibility.append({"check": "matrix_combos", "baseline": base_combos, "current": cur_combos})
        reasons.append("matrix 组合不一致：禁止跨 generator 或 optimizer 模式比较")

    cur_summary = current.get("summary", {})
    base_summary = baseline.get("summary", {})
    cur_overall = cur_summary.get("overall_score", 0.0)
    base_overall = base_summary.get("overall_score", 0.0)
    overall_delta = cur_overall - base_overall

    dimension_regressions: list[dict] = []
    cur_dims = cur_summary.get("by_dimension", {})
    base_dims = baseline.get("by_dimension", {}) or base_summary.get("by_dimension", {})
    for dim, base_val in base_dims.items():
        cur_val = cur_dims.get(dim, 0.0)
        drop = base_val - cur_val
        if drop > max_dimension_drop:
            dimension_regressions.append({
                "dimension": dim,
                "baseline": base_val,
                "current": cur_val,
                "drop": drop,
            })

    base_cases = baseline.get("cases", {})
    cur_cases = current.get("cases", {})
    case_regressions: list[dict] = []
    new_failures: list[dict] = []
    missing_cases: list[dict] = []
    for key, base_entry in base_cases.items():
        base_score = base_entry.get("overall", 0.0)
        base_passed = base_entry.get("passed", False)
        cur_entry = cur_cases.get(key)
        if cur_entry is None:
            # Baseline 中存在、当前缺失的组合 → 回退（不再静默跳过）。
            missing_cases.append({
                "key": key,
                "case_id": base_entry.get("case_id", key),
                "baseline_score": base_score,
            })
            continue
        cur_score = cur_entry.get("overall", 0.0)
        cur_passed = cur_entry.get("passed", False)
        drop = base_score - cur_score
        if drop > max_case_drop:
            case_regressions.append({
                "case_id": base_entry.get("case_id", key),
                "key": key,
                "baseline": base_score,
                "current": cur_score,
                "drop": drop,
            })
        if base_passed and not cur_passed:
            new_failures.append({
                "case_id": base_entry.get("case_id", key),
                "key": key,
                "baseline_score": base_score,
                "current_score": cur_score,
                "current_status": cur_entry.get("status"),
            })

    passed = (
        not compatibility
        and overall_delta >= 0
        and not dimension_regressions
        and not case_regressions
        and not new_failures
        and not missing_cases
    )

    return {
        "passed": passed,
        "overall_delta": overall_delta,
        "baseline_overall": base_overall,
        "current_overall": cur_overall,
        "compatibility": compatibility,
        "reasons": reasons,
        "dimension_regressions": dimension_regressions,
        "case_regressions": case_regressions,
        "new_failures": new_failures,
        "missing_cases": missing_cases,
    }
