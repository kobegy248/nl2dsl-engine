"""V2 语义基准测试 CLI —— 真实查询链路 + rule/llm × optimizer ON/OFF 矩阵。

Phase 1+2 重构：

- actual DSL 来自真实 ``/api/v1/query`` 调用（:class:`ApiEvaluationExecutor`），
  不再从 ``expected`` 构造。
- 支持 ``--generator rule|llm|all`` 与 ``--optimizer on|off|all`` 矩阵。
- 支持 ``--domain`` / ``--tags`` 过滤。
- 每个矩阵组合独立构建 App/Executor，避免共享 sticky fallback 状态。
- 支持 Baseline 保存 / 读取 / 回归门禁。
- 报告同时输出 JSON 与 Markdown（同源结构化模型）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

from nl2dsl.evaluation.baseline import (
    BASELINE_SCHEMA_VERSION,
    compute_dataset_hash,
    evaluate_regression,
    load_baseline,
    save_baseline,
)
from nl2dsl.evaluation.dataset import V2DatasetLoader
from nl2dsl.evaluation.execution import (
    ApiEvaluationExecutor,
    DomainAppConfig,
    ExecutorConfig,
)
from nl2dsl.evaluation.v2_reporter import V2Reporter
from nl2dsl.evaluation.v2_runner import V2BenchmarkRunner
from nl2dsl.evaluation.canonical.resolver import CanonicalResolver
from nl2dsl.evaluation.scorers.intent_scorer import IntentScorer
from nl2dsl.evaluation.scorers.metric_scorer import MetricScorer
from nl2dsl.evaluation.scorers.filter_scorer import FilterScorer
from nl2dsl.evaluation.scorers.planner_scorer import PlannerScorer
from nl2dsl.evaluation.scorers.governance_scorer import GovernanceScorer
from nl2dsl.utils.logger import get_logger

logger = get_logger("evaluation.v2_cli")


def _load_config(config_path: Path) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_scorers(resolver: CanonicalResolver) -> dict:
    return {
        "intent_scorer": IntentScorer(),
        "metric_scorer": MetricScorer(resolver.metric),
        "filter_scorer": FilterScorer(resolver),
        "planner_scorer": PlannerScorer(resolver),
        "governance_scorer": GovernanceScorer(),
    }


def _samples_dir() -> Path:
    """正式包内置样例配置目录（不依赖 tests/）。"""
    return Path(__file__).resolve().parent / "samples"


# 默认多领域环境：每个业务领域独立的样例数据库 / 注册表 / 权限 / 评测身份。
# eval_user_id / eval_tenant_id 与各领域样例 permissions.yaml 中的用户对齐，
# 保证治理注入（行级权限）真实生效。
_DEFAULT_DOMAIN_SPECS: dict[str, dict] = {
    "ecommerce": {
        "metrics_file": "metrics.yaml",
        "permissions_file": "permissions.yaml",
        "eval_user_id": "u001",
        "eval_tenant_id": "t001",
        "create_engine": "create_mock_database",
    },
    "bank": {
        "metrics_file": "bank_metrics.yaml",
        "permissions_file": "bank_permissions.yaml",
        "eval_user_id": "b001",
        "eval_tenant_id": "t001",
        "create_engine": "create_mock_bank_database",
    },
    "supply_chain": {
        "metrics_file": "supply_chain_metrics.yaml",
        "permissions_file": "supply_chain_permissions.yaml",
        "eval_user_id": "sc001",
        "eval_tenant_id": "t001",
        "create_engine": "create_mock_supply_chain_database",
    },
}


def _build_domain_config(domain: str, samples: Path) -> DomainAppConfig:
    """从内置样例构建单个业务领域的执行环境配置。"""
    from nl2dsl.testing import sample_data

    spec = _DEFAULT_DOMAIN_SPECS[domain]
    create_engine = getattr(sample_data, spec["create_engine"])
    engine, *_ = create_engine("sqlite:///:memory:")

    registry = yaml.safe_load(
        (samples / spec["metrics_file"]).read_text(encoding="utf-8")
    )
    perm_data = yaml.safe_load(
        (samples / spec["permissions_file"]).read_text(encoding="utf-8")
    )
    permissions = perm_data.get("users", {})
    sensitive_columns = perm_data.get("sensitive_columns", {})
    masking_rules = perm_data.get("masking_rules", {})
    # 权限并入 registry_dict，供 optimizer 治理规则读取。
    registry_dict = {
        "metrics": registry.get("metrics", {}),
        "dimensions": registry.get("dimensions", {}),
        "data_sources": registry.get("data_sources", {}),
        "permissions": permissions,
    }
    return DomainAppConfig(
        domain=domain,
        engine=engine,
        registry_dict=registry_dict,
        permissions=permissions,
        sensitive_columns=sensitive_columns,
        masking_rules=masking_rules,
        eval_user_id=spec["eval_user_id"],
        eval_tenant_id=spec["eval_tenant_id"],
    )


def build_default_executor_config(config_path: Path | None = None) -> ExecutorConfig:
    """构建默认 ExecutorConfig。

    默认构造**真实多领域**环境：ecommerce / bank / supply_chain 各自独立的样例
    数据库、语义注册表、权限与评测身份。用例按 ``case.domain`` 路由到对应领域，
    未知领域由执行器明确返回 error（不静默回退 ecommerce）。

    传入 ``config_path`` 时退化为单领域 ecommerce 覆盖（兼容旧用法）：使用该
    自定义 registry + 内置 ecommerce 样例数据/权限。

    使 ``python -m nl2dsl.evaluation.v2_cli`` 无需外部数据库即可运行真实
    rule 模式评测（使用正式包内置样例数据与配置，不依赖 ``tests.*``）。
    LLM Client 仅在 ``NL2DSL_LLM_API_KEY`` 存在时构建。
    """
    samples = _samples_dir()

    # 显式单领域覆盖（兼容）：自定义 registry + ecommerce 样例数据/权限。
    if config_path and config_path.exists():
        from nl2dsl.testing.sample_data import create_mock_database

        engine, *_ = create_mock_database("sqlite:///:memory:")
        registry_dict = _load_config(config_path)
        perm_data = yaml.safe_load(
            (samples / "permissions.yaml").read_text(encoding="utf-8")
        )
        permissions = perm_data.get("users", {})
        sensitive_columns = perm_data.get("sensitive_columns", {})
        masking_rules = perm_data.get("masking_rules", {})
        registry_dict = {
            "metrics": registry_dict.get("metrics", {}),
            "dimensions": registry_dict.get("dimensions", {}),
            "data_sources": registry_dict.get("data_sources", {}),
            "permissions": permissions,
        }
        return ExecutorConfig(
            engine=engine,
            registry_dict=registry_dict,
            permissions=permissions,
            sensitive_columns=sensitive_columns,
            masking_rules=masking_rules,
            llm_client=_maybe_llm_client(),
            default_domain="ecommerce",
        )

    # 默认：三领域真实多领域环境。
    domains = {
        name: _build_domain_config(name, samples)
        for name in _DEFAULT_DOMAIN_SPECS
    }
    return ExecutorConfig(
        domains=domains,
        default_domain="ecommerce",
        llm_client=_maybe_llm_client(),
    )


def _maybe_llm_client():
    """从当前激活的 provider 构建 LLM Client，未配置则返回 None。

    通过 ``NL2DSL_LLM_PROVIDER`` 选择 provider（默认 ``default``，
    即平铺字段 NL2DSL_LLM_API_KEY / _BASE_URL / _MODEL）。
    """
    from nl2dsl.llm.providers import get_llm_client

    return get_llm_client()


def _expand_matrix(generator: str, optimizer: str) -> list[tuple[str, bool]]:
    """展开矩阵组合 (generator_mode, optimizer_enabled)。"""
    gens = ["rule", "llm"] if generator == "all" else [generator]
    opts = [True, False] if optimizer == "all" else [optimizer == "on"]
    return [(g, o) for g in gens for o in opts]


def _filter_cases(cases, domain: str | None, tags: list[str] | None):
    if domain:
        cases = [c for c in cases if (c.domain or "") == domain]
    if tags:
        tag_set = set(tags)
        cases = [c for c in cases if tag_set & set(c.tags or [])]
    return cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="运行 V2 语义查询基准测试（真实链路 + 矩阵 + 回归门禁）",
    )
    parser.add_argument("--dataset", type=Path, required=True, help="V2 数据集目录路径")
    parser.add_argument(
        "--config", type=Path, default=None,
        help="项目配置文件路径（默认：使用 e2e fixtures 的 metrics_test.yaml）",
    )
    parser.add_argument("--output", type=Path, default=Path("reports/v2"), help="输出目录")
    parser.add_argument("--format", choices=["console", "markdown", "json", "both"], default="both")

    # 矩阵
    parser.add_argument("--generator", choices=["rule", "llm", "all"], default="rule",
                        help="生成模式（默认：rule，无需 LLM）")
    parser.add_argument("--optimizer", choices=["on", "off", "all"], default="off",
                        help="Optimizer 开关（默认：off）")

    # 过滤
    parser.add_argument("--domain", type=str, default=None, help="按 domain 过滤")
    parser.add_argument("--tags", type=str, default=None, help="按 tag 过滤（逗号分隔）")

    # Baseline / 回归
    parser.add_argument("--save-baseline", type=Path, default=None, help="将本次报告保存为 Baseline")
    parser.add_argument("--baseline", type=Path, default=None, help="对比 Baseline 路径")
    parser.add_argument("--fail-on-regression", action="store_true", help="回退时返回非零退出码")
    parser.add_argument("--max-dimension-drop", type=float, default=0.02, help="维度最大允许下降（默认 0.02）")
    parser.add_argument("--max-case-drop", type=float, default=0.10, help="单用例最大允许下降（默认 0.10）")
    parser.add_argument(
        "--fail-on-execution-error", action="store_true",
        help="出现任意执行错误（status=error）即返回非零退出码（默认仅在全错误/递归/无可评分时非零）",
    )

    args = parser.parse_args(argv)

    # 加载配置 / 解析器 / 评分器
    if args.config:
        config = _load_config(args.config)
    else:
        samples = _samples_dir()
        config = yaml.safe_load((samples / "metrics.yaml").read_text(encoding="utf-8"))
    resolver = CanonicalResolver.from_config(config)
    scorers = _build_scorers(resolver)
    runner = V2BenchmarkRunner(scorers)  # injected_filters 在拿到 executor 后补设

    # 加载数据集 + 过滤
    loader = V2DatasetLoader(args.dataset)
    cases = loader.load_all()
    if not cases:
        print("错误：未找到测试用例。", file=sys.stderr)
        return 1
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else None
    cases = _filter_cases(cases, args.domain, tags)
    if not cases:
        print("错误：过滤后无测试用例。", file=sys.stderr)
        return 1
    print(f"已加载 {len(cases)} 条测试用例")

    # 构建执行器配置
    exec_config = build_default_executor_config(args.config)
    executor = ApiEvaluationExecutor(exec_config)
    # 将治理注入过滤器交给 runner，评分前剥离
    runner.injected_filters = executor.injected_filters

    matrix_combos = _expand_matrix(args.generator, args.optimizer)
    print(f"矩阵组合：{[(g, 'on' if o else 'off') for g, o in matrix_combos]}")

    all_results: list[dict] = []
    matrix_runs: list[dict] = []
    for gen_mode, opt_on in matrix_combos:
        print(f"\n=== generator={gen_mode} optimizer={'on' if opt_on else 'off'} ===")
        results = runner.run_matrix(
            cases, executor, resolver,
            generator_mode=gen_mode, optimizer_enabled=opt_on,
        )
        matrix_runs.append({
            "generator_mode": gen_mode,
            "optimizer_enabled": opt_on,
            "results": results,
        })
        all_results.extend(results)
        passed = sum(1 for r in results if r.get("passed"))
        print(f"  通过 {passed}/{len(results)}")

    # 构建结构化报告
    reporter = V2Reporter()
    report = reporter.build_matrix_report(all_results, matrix_runs=matrix_runs)
    # 注入身份字段，供回归对比做数据集/模式身份校验（fail-closed）。
    report["dataset_hash"] = compute_dataset_hash(cases)
    report["schema_version"] = BASELINE_SCHEMA_VERSION

    # 回归对比
    regression = None
    if args.baseline:
        baseline = load_baseline(args.baseline)
        regression = evaluate_regression(
            report, baseline,
            max_dimension_drop=args.max_dimension_drop,
            max_case_drop=args.max_case_drop,
        )
        report["regression"] = regression
        print(f"\n回归门禁：{'通过' if regression['passed'] else '失败'}"
              f"（overall delta {regression['overall_delta']:+.1%}）")
        if not regression["passed"]:
            for reason in regression.get("reasons", []):
                print(f"  - {reason}")

    # 保存（原子写入 + 立即回读校验，保证报告是严格合法 JSON）
    args.output.mkdir(parents=True, exist_ok=True)
    json_path = args.output / "benchmark_report.json"
    md_path = args.output / "benchmark_report.md"
    json_text = reporter.matrix_report_to_json(report)
    if not _write_and_verify_json(json_path, json_text):
        print(f"错误：报告 JSON 写入后回读校验失败：{json_path}", file=sys.stderr)
        return 1
    md_path.write_text(reporter.matrix_report_to_markdown(report, regression=regression), encoding="utf-8")
    print(f"\n报告已保存至：{json_path} / {md_path}")

    if args.save_baseline:
        save_baseline(report, cases, args.save_baseline, matrix={
            "generator": args.generator, "optimizer": args.optimizer,
        })
        print(f"Baseline 已保存至：{args.save_baseline}")

    # 顺带生成质量报告（复用本次评测填充的 Audit/Feedback 表）
    _emit_quality_report(exec_config, report, args.output)

    # ------------------------------------------------------------------
    # 退出码：区分语义低分 / 用例失败 / 评测基础设施异常
    # ------------------------------------------------------------------
    summary = report.get("summary", {})
    total = summary.get("total_cases", 0)
    passed = summary.get("passed", 0)
    execution_errors = summary.get("execution_errors", 0)
    recursion_errors = summary.get("recursion_errors", 0)
    unavailable = summary.get("unavailable", 0)
    scoreable = total - unavailable - execution_errors

    # Baseline 回归门禁：回退时非零。
    if args.fail_on_regression and regression is not None and not regression["passed"]:
        return 1

    # 评测基础设施异常必须非零退出，即便没有启用 --fail-on-regression：
    # - 出现 GRAPH_RECURSION_LIMIT（评测链路死循环，非语义问题）
    # - 全部用例均为 error（评测链路完全不可用）
    # - 没有任何可评分结果（无可评分用例）
    if recursion_errors > 0:
        print(
            f"错误：检测到 {recursion_errors} 个 GRAPH_RECURSION_LIMIT，评测链路异常，返回非零退出码。",
            file=sys.stderr,
        )
        return 1
    if total > 0 and execution_errors == total:
        print("错误：全部用例均为执行错误（status=error），评测链路异常，返回非零退出码。", file=sys.stderr)
        return 1
    if scoreable <= 0 and total > 0:
        print("错误：没有任何可评分结果，评测链路异常，返回非零退出码。", file=sys.stderr)
        return 1

    # 显式 --fail-on-execution-error：任一执行错误即非零。
    if args.fail_on_execution_error and execution_errors > 0:
        print(f"错误：{execution_errors} 个执行错误，--fail-on-execution-error 已启用，返回非零退出码。", file=sys.stderr)
        return 1

    return 0


def _write_and_verify_json(path: Path, text: str) -> bool:
    """原子写入 JSON 并立即回读校验；失败不覆盖既有有效报告。"""
    import json
    import os
    import tempfile

    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent),
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(text)
        # 回读校验：必须能被标准 JSON parser 解析。
        with open(tmp_name, "r", encoding="utf-8") as f:
            json.load(f)
        os.replace(tmp_name, path)
        return True
    except Exception as exc:
        logger.error("JSON 报告写入/回读校验失败：%s", exc)
        # 不覆盖既有有效报告：清理临时文件后返回失败。
        try:
            os.remove(tmp_name)
        except OSError:
            pass
        return False


def _emit_quality_report(exec_config: ExecutorConfig, evaluation_report: dict, output_dir: Path) -> None:
    """从评测引擎的 Audit/Feedback 表 + 矩阵报告生成质量报告。"""
    from nl2dsl.audit.logger import AuditLogger
    from nl2dsl.feedback.store import FeedbackStore
    from nl2dsl.quality.analyzer import (
        analyze_audit, analyze_evaluation, analyze_feedback,
    )
    from nl2dsl.quality.report import (
        build_quality_report, quality_report_to_json, quality_report_to_markdown,
    )

    # 多领域模式下 flat engine 为 None：取默认领域的引擎生成质量报告
    # （各领域 Audit 表独立，质量报告覆盖默认领域；矩阵评测结果已在 evaluation_report 中）。
    engine = exec_config.engine
    if engine is None:
        dc = exec_config.get_domain_config(exec_config.default_domain)
        engine = dc.engine if dc is not None else None
    if engine is None:
        # 无可用引擎（极端配置）：跳过质量报告，不阻断主评测流程。
        logger.warning("无可用的 Audit 引擎，跳过质量报告生成")
        return

    audit_logger = AuditLogger(engine)
    feedback_store = FeedbackStore(engine, audit_logger)
    quality = build_quality_report(
        evaluation=analyze_evaluation(evaluation_report),
        audit=analyze_audit(audit_logger),
        feedback=analyze_feedback(feedback_store, audit_logger),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "quality_report.json").write_text(
        quality_report_to_json(quality), encoding="utf-8",
    )
    (output_dir / "quality_report.md").write_text(
        quality_report_to_markdown(quality), encoding="utf-8",
    )
    print(f"质量报告已保存至：{output_dir}/quality_report.{{json,md}}")


if __name__ == "__main__":
    sys.exit(main())
