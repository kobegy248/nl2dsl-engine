# NL2DSL 质量报告

- 生成时间：2026-06-20T07:49:19.129169
- schema_version：1.0

## Evaluation

- 整体准确率：50.0%
- 用例数：10（通过 5 / 失败 5 / 不可用 0）
- 失败用例数：5

### 各维度

| 维度 | 准确率 |
|------|--------|
| intent | 50.0% |
| metric | 50.0% |
| filter | 50.0% |
| planner | 50.0% |
| governance | 50.0% |

### 矩阵

| Generator | Optimizer | Overall | Passed | Total |
|-----------|-----------|---------|--------|-------|
| rule | off | 50.0% | 5 | 10 |

## Audit

- 查询总数：0
- 状态分布：{}
- 路径分布：{}
- 延迟 P50：0.0 ms | P95：0.0 ms
- Trace 完整率：0.0%
- 字段完整率：DSL 0.0% / SQL 0.0% / Trace 0.0%

## Feedback

- 反馈总数：0
- 负反馈率：0.0%
- 审计关联率：0.0%
- corrected_dsl 覆盖率：0.0%
- 候选评测用例数：0