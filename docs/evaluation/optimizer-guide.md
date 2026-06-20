# Semantic Query Optimizer — 使用指南

## 概述

Semantic Query Optimizer 是一个基于规则引擎的 DSL 语义优化器，自动检测和修正 26 种语义错误。

## 快速开始

```python
from nl2dsl.optimizer import optimize
from nl2dsl.optimizer.context import SemanticConfig

# 从 YAML 配置加载语义层
config = SemanticConfig.from_registry_dict(yaml_config)

# 优化 DSL
optimized_dsl, report = optimize(
    raw_dsl,
    semantic_config=config,
    user_role="analyst",
    original_question="本月华东区GMV",
)

# 查看优化报告
print(report.to_json())
```

## CLI 评估

第五周起，V2 CLI 改为**真实查询链路**评测：actual DSL 来自真实 `/api/v1/query`，
Optimizer 的开关通过 `--optimizer on|off|all` 显式控制。OFF 时图中不注册
`optimize_dsl` 节点，Trace 中也不会出现该步骤。

```bash
# Optimizer ON（rule 生成 + 优化）
python -m nl2dsl.evaluation.v2_cli \
  --dataset tests/evaluation/dataset/v2 --generator rule --optimizer on

# 矩阵全量（rule/llm × on/off）
python -m nl2dsl.evaluation.v2_cli \
  --dataset tests/evaluation/dataset/v2 --generator all --optimizer all

# Baseline 保存 + 回归门禁
python -m nl2dsl.evaluation.v2_cli --dataset ... --generator rule --optimizer on \
  --save-baseline reports/baselines/rule-optimizer-on.json
python -m nl2dsl.evaluation.v2_cli --dataset ... --generator rule --optimizer on \
  --baseline reports/baselines/rule-optimizer-on.json --fail-on-regression
```

报告中的 `optimizer_stats`（avg_fixes / avg_warnings / avg_rejections /
avg_elapsed_ms）从真实 Trace 的 `optimize_dsl` 步骤聚合。Optimizer 关闭时该统计为
`null`。

> **矩阵结果按组合身份保存（修复）**：报告 `cases` 以
> `domain + case_id + generator + optimizer` 为键，同一用例四种组合互不覆盖；
> `by_matrix` 列出每个组合的总数 / 通过 / 不可用 / 整体分数。Baseline 比较前校验
> `dataset_hash` 与 `matrix_combos`，禁止跨模式比较，不兼容即门禁失败。

> 注：旧版的 `--rules` / `--disable-rules` / `--compare` / `--verbose-optimizer`
> 单规则 A/B 开关在第五周重构中移除。需要按规则子集评估时，可直接调用
> `nl2dsl.optimizer.optimize(..., enabled_rules=..., disabled_rules=...)`。

## 规则分类

| 优先级 | 名称 | 规则数 | 说明 |
|--------|------|--------|------|
| P1 | Block | 3 | 结构阻断（S001, S002, I001）— 失败则立即终止 |
| P2 | Identity | 4 | 确定性修正（M001, M003, D003, F002） |
| P3 | Consistency | 4 | 跨组件一致性（M004, I002, D002, F001） |
| P4 | Auth | 2 | 权限检查（G001, G002） |
| P5 | Completeness | 11 | 补全警告（M002, D001, F003-F005, P001-P004, T001-T002） |
| P6 | Ambiguity | 2 | 歧义检测（A001, A002）— Clarification Required |

## 解读 OptimizationReport

```json
{
  "report_id": "abc123",
  "total_rules_checked": 26,
  "total_rules_triggered": 4,
  "fixes_applied": [...],
  "warnings_issued": [...],
  "rejections": [...],
  "fix_rate": 0.50,
  "fatal": false,
  "elapsed_ms": 12,
  "diff": ["metrics[0].func: avg → sum"]
}
```

- `fixes_applied`: 自动修正的规则结果
- `warnings_issued`: 警告（不自动修正）
- `rejections`: 拒绝（需要人工介入或 LLM 修正）
- `fatal`: 是否被致命拒绝阻断
- `fix_rate`: 自动修正率
