"""质量报告分析器：汇总 Evaluation / Audit / Feedback 三类信息。"""

from __future__ import annotations

import json
import statistics
from typing import Any

from sqlalchemy import text

from nl2dsl.audit.logger import AuditLogger
from nl2dsl.feedback.store import FeedbackStore


# 按路径要求的 Trace 关键节点
SUCCESS_PATH_NODES = [
    "generate_dsl", "validate_dsl", "resolve_semantic",
    "build_sql", "scan_sql", "execute_sql",
]
OPTIMIZER_NODE = "optimize_dsl"
CLARIFICATION_NODES = ["clarification"]
AGENT_NODE = "agent"
# Agent / 复杂查询路径除 agent 节点外，至少需要一条子查询执行证据，避免单节点 Trace 被判完整。
# 这些名称与 AgentOrchestrator 实际生产的 Trace 步骤一致（sub_query_end 携带子查询执行状态），
# 也保留 graph 内节点名（build_sql / execute_sql / scan_sql）以便子查询 trace 被透传时同样识别。
AGENT_EXECUTION_NODES = {
    "build_sql", "execute_sql", "scan_sql",
    "sub_query", "subquery", "sub_query_start", "sub_query_end",
}


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return float(sorted_vals[f])
    return float(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f))


def _trace_items(trace: Any) -> list[dict]:
    """Normalize a trace field into a list of step dicts."""
    if not trace:
        return []
    if isinstance(trace, str):
        try:
            trace = json.loads(trace)
        except Exception:
            return []
    if isinstance(trace, list):
        return [it for it in trace if isinstance(it, dict)]
    return []


def _trace_steps(trace: Any) -> set[str]:
    return {it.get("step") for it in _trace_items(trace) if it.get("step")}


def _classify_path(steps: set[str], status: str) -> str:
    """路径分类（每种路径有明确的最小节点集合）。

    - ``clarification``：澄清路径
    - ``agent``：Agent / 复杂查询路径
    - ``error``：失败路径
    - ``success_with_optimizer``：含 Optimizer 的成功路径
    - ``success``：普通成功路径
    - ``unknown``：无法识别（默认计为不完整）
    """
    if status == "clarification" or CLARIFICATION_NODES[0] in steps:
        return "clarification"
    if AGENT_NODE in steps:
        return "agent"
    if status in ("error", "failed"):
        return "error"
    if OPTIMIZER_NODE in steps:
        return "success_with_optimizer"
    if SUCCESS_PATH_NODES[0] in steps:
        return "success"
    return "unknown"


def _agent_path_complete(items: list[dict], status: str) -> bool:
    """Agent / 复杂查询路径完整性（第三轮审阅 P1）。

    ``sub_query_start`` 只证明子查询开始，**不**证明执行完成；成功路径必须：

    - 含 ``agent`` 与 ``plan`` 步骤；
    - 每个已开始的子查询（``sub_query_start``）都有按 ``sub_query_id`` 匹配的
      ``sub_query_end``（start/end 数量与 ID 都要匹配）；
    - 至少一条 ``sub_query_end``（执行证据），不接受仅有 ``sub_query_start`` 或
      仅有一个 ``agent``/``execute_sql`` 节点；
    - 含 ``aggregation`` 或 ``explanation``。

    error 路径允许失败的 ``sub_query_end``（携带 ``status=error`` / ``error``），
    视为保留了失败信息即可计完整；无 ``sub_query_end`` 时退化为“非空 Trace”。
    """
    steps = {it.get("step") for it in items if it.get("step")}
    if AGENT_NODE not in steps:
        return False
    starts = [it for it in items if it.get("step") == "sub_query_start"]
    ends = [it for it in items if it.get("step") == "sub_query_end"]
    start_ids = {it.get("sub_query_id") for it in starts}
    end_ids = {it.get("sub_query_id") for it in ends}

    if status in ("success", "warning"):
        if "plan" not in steps:
            return False
        # 每个 start 都要有匹配 ID 的 end
        if starts and not start_ids.issubset(end_ids):
            return False
        # 必须有至少一条 sub_query_end 作为执行证据
        if not ends:
            return False
        if not ({"aggregation", "explanation"} & steps):
            return False
        return True

    # error / 其它：失败信息保留即计完整
    if ends:
        return any(it.get("status") == "error" or it.get("error") for it in ends)
    return bool(steps)


def _path_complete(
    path: str, items: list[dict], status: str, optimizer_enabled_hint: bool,
) -> bool:
    """判定该路径 Trace 是否完整。

    任何路径的空 Trace 一律计为不完整；``unknown`` 默认不完整。
    """
    steps = {it.get("step") for it in items if it.get("step")}
    if not steps:
        return False
    if path == "clarification":
        return CLARIFICATION_NODES[0] in steps
    if path == "agent":
        return _agent_path_complete(items, status)
    if path == "error":
        # 失败路径：至少捕获了非空 Trace（错误可能发生在任意步骤）
        return bool(steps)
    if path in ("success", "success_with_optimizer"):
        required = set(SUCCESS_PATH_NODES)
        if path == "success_with_optimizer" or optimizer_enabled_hint:
            required.add(OPTIMIZER_NODE)
        return required.issubset(steps)
    # unknown / other：默认不完整
    return False


def analyze_audit(audit_logger: AuditLogger) -> dict:
    """从审计日志统计状态分布、延迟、Trace 完整率与字段完整率。"""
    with audit_logger._engine.connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(
            text("SELECT * FROM nl2dsl_audit_log")
        )]

    total = len(rows)
    status_dist: dict[str, int] = {}
    latencies: list[int] = []
    trace_complete = 0
    dsl_present = 0
    sql_present = 0
    trace_present = 0
    path_dist: dict[str, int] = {}
    # 每条路径的总数 / 完整数，用于定位 Trace 缺失集中在哪条路径
    path_totals: dict[str, int] = {}
    path_complete: dict[str, int] = {}

    for row in rows:
        status = row.get("status") or "unknown"
        status_dist[status] = status_dist.get(status, 0) + 1

        if row.get("execution_time_ms") is not None:
            latencies.append(int(row["execution_time_ms"]))

        trace_raw = row.get("trace_json")
        items = _trace_items(trace_raw)
        steps = {it.get("step") for it in items if it.get("step")}
        if trace_raw:
            trace_present += 1
        if row.get("dsl_json"):
            dsl_present += 1
        if row.get("sql_text"):
            sql_present += 1

        path = _classify_path(steps, status)
        path_dist[path] = path_dist.get(path, 0) + 1
        path_totals[path] = path_totals.get(path, 0) + 1
        # optimizer 是否应出现：仅当路径含 optimizer 时要求
        complete = _path_complete(
            path, items, status,
            optimizer_enabled_hint=(OPTIMIZER_NODE in steps),
        )
        if complete:
            trace_complete += 1
            path_complete[path] = path_complete.get(path, 0) + 1

    path_completeness: dict[str, dict] = {}
    for p, t in path_totals.items():
        c = path_complete.get(p, 0)
        path_completeness[p] = {
            "total": t,
            "complete": c,
            "rate": (c / t) if t else 0.0,
        }

    latencies_sorted = sorted(latencies)
    return {
        "total_queries": total,
        "status_distribution": status_dist,
        "path_distribution": path_dist,
        "path_completeness": path_completeness,
        "latency": {
            "p50_ms": _percentile(latencies_sorted, 0.5),
            "p95_ms": _percentile(latencies_sorted, 0.95),
            "avg_ms": (sum(latencies) / len(latencies)) if latencies else 0.0,
        },
        "trace_completeness": (trace_complete / total) if total else 0.0,
        "field_completeness": {
            "dsl": (dsl_present / total) if total else 0.0,
            "sql": (sql_present / total) if total else 0.0,
            "trace": (trace_present / total) if total else 0.0,
        },
    }


def analyze_feedback(store: FeedbackStore | None, audit_logger: AuditLogger) -> dict:
    """从反馈表统计负反馈率、关联率、issue_type Top N、corrected_dsl 覆盖率、候选数。"""
    if store is None:
        return {
            "total": 0, "negative_rate": 0.0, "audit_link_rate": 0.0,
            "issue_type_top": [], "corrected_dsl_coverage": 0.0, "candidates": 0,
        }

    records, _ = store.list(limit=100000, offset=0)
    total = len(records)
    if total == 0:
        return {
            "total": 0, "negative_rate": 0.0, "audit_link_rate": 0.0,
            "issue_type_top": [], "corrected_dsl_coverage": 0.0, "candidates": 0,
        }

    negative = sum(1 for r in records if not r.is_correct)
    with_dsl = sum(1 for r in records if r.corrected_dsl)
    linked = 0
    issue_counts: dict[str, int] = {}
    candidate_keys: set[str] = set()

    for rec in records:
        audit = audit_logger.get_query(rec.query_id)
        if audit is not None:
            linked += 1
        itype = rec.issue_type or "other"
        issue_counts[itype] = issue_counts.get(itype, 0) + 1
        if rec.corrected_dsl and not rec.is_correct:
            # 候选去重键（query + corrected_dsl）
            q = (audit or {}).get("question") or ""
            key = json.dumps({"q": q, "dsl": rec.corrected_dsl}, sort_keys=True)
            candidate_keys.add(key)

    top = sorted(issue_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    return {
        "total": total,
        "negative_rate": negative / total,
        "audit_link_rate": linked / total,
        "issue_type_top": [{"issue_type": k, "count": v} for k, v in top],
        "corrected_dsl_coverage": with_dsl / total,
        "candidates": len(candidate_keys),
    }


def analyze_evaluation(report: dict | None) -> dict:
    """从 V2 矩阵报告提取评测分数与回退信息。"""
    if not report:
        return {"available": False}
    s = report.get("summary", {})
    return {
        "available": True,
        "overall_score": s.get("overall_score", 0.0),
        "total_cases": s.get("total_cases", 0),
        "passed": s.get("passed", 0),
        "failed": s.get("failed", 0),
        "unavailable": s.get("unavailable", 0),
        "by_dimension": s.get("by_dimension", {}),
        "by_matrix": report.get("by_matrix", []),
        "optimizer_stats": report.get("optimizer_stats"),
        "failed_cases": len(report.get("failed_cases", [])),
    }
