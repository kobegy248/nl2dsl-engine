# NL2DSL 质量报告

- 生成时间：2026-06-19T17:10:53.690851
- schema_version：1.0

## Evaluation

- 整体准确率：81.6%
- 用例数：44（通过 18 / 失败 26 / 不可用 0）
- 失败用例数：26

### 各维度

| 维度 | 准确率 |
|------|--------|
| intent | 95.5% |
| metric | 100.0% |
| filter | 81.8% |
| planner | 56.6% |
| governance | 100.0% |

### 矩阵

| Generator | Optimizer | Overall | Passed | Total |
|-----------|-----------|---------|--------|-------|
| rule | on | 81.6% | 9 | 22 |
| rule | off | 81.6% | 9 | 22 |

## Audit

- 查询总数：44
- 状态分布：{'success': 41, 'warning': 3}
- 路径分布：{'clarification': 42, 'agent': 2}
- 延迟 P50：19.0 ms | P95：31.9 ms
- Trace 完整率：95.5%
- 字段完整率：DSL 95.5% / SQL 95.5% / Trace 100.0%

## Feedback

- 反馈总数：0
- 负反馈率：0.0%
- 审计关联率：0.0%
- corrected_dsl 覆盖率：0.0%
- 候选评测用例数：0