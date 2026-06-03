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

```bash
# 启用 Optimizer
python -m nl2dsl.evaluation.v2_cli --dataset tests/evaluation/dataset --optimizer on

# 对比模式：Baseline vs Optimized
python -m nl2dsl.evaluation.v2_cli --dataset tests/evaluation/dataset --compare

# 仅启用特定规则
python -m nl2dsl.evaluation.v2_cli --dataset tests/evaluation/dataset --optimizer on --rules M001,F001,P003

# 禁用特定规则（A/B 测试）
python -m nl2dsl.evaluation.v2_cli --dataset tests/evaluation/dataset --optimizer on --disable-rules A001,A002

# 输出优化详情
python -m nl2dsl.evaluation.v2_cli --dataset tests/evaluation/dataset --optimizer on --verbose-optimizer
```

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
