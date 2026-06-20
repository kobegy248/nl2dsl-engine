# NL2DSL 质量报告

- 生成时间：2026-06-20T07:55:59.202676
- schema_version：1.0

## Evaluation

- 整体准确率：92.6%
- 用例数：55（通过 42 / 失败 13 / 不可用 0）
- 失败用例数：13

### 各维度

| 维度 | 准确率 |
|------|--------|
| intent | 98.2% |
| metric | 100.0% |
| filter | 92.7% |
| planner | 82.6% |
| governance | 100.0% |

### 矩阵

| Generator | Optimizer | Overall | Passed | Total |
|-----------|-----------|---------|--------|-------|
| rule | off | 92.6% | 42 | 55 |

## Audit

- 查询总数：55
- 状态分布：{'success': 55}
- 路径分布：{'clarification': 51, 'agent': 4}
- 延迟 P50：19.0 ms | P95：28.3 ms
- Trace 完整率：100.0%
- 字段完整率：DSL 92.7% / SQL 92.7% / Trace 100.0%

## Feedback

- 反馈总数：0
- 负反馈率：0.0%
- 审计关联率：0.0%
- corrected_dsl 覆盖率：0.0%
- 候选评测用例数：0