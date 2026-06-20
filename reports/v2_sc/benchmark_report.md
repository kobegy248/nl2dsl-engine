# NL2DSL V2 评测报告

- 生成时间：2026-06-20T07:49:28.344983
- schema_version：1.0

## 总览

- 用例数：10
- 通过：10 | 失败：0 | 不可用：0
- 整体准确率：100.0%
- 平均延迟：0.0 ms | P50：0.0 ms | P95：0.0 ms

## 各维度

| 维度 | 准确率 |
|------|--------|
| intent | 100.0% |
| metric | 100.0% |
| filter | 100.0% |
| planner | 100.0% |
| governance | 100.0% |

## 按矩阵（generator × optimizer）

| Generator | Optimizer | Total | Passed | Unavailable | Overall |
|-----------|-----------|-------|--------|-------------|---------|
| rule | off | 10 | 10 | 0 | 100.0% |

## 按 Domain

| Domain | Total | Passed | Failed | Overall |
|--------|-------|--------|--------|---------|
| supply_chain | 10 | 10 | 0 | 100.0% |

## 按 Tag

| Tag | Total | Passed | Failed | Overall |
|-----|-------|--------|--------|---------|
| avg | 2 | 2 | 0 | 100.0% |
| basic | 3 | 3 | 0 | 100.0% |
| delivery | 1 | 1 | 0 | 100.0% |
| dimension | 5 | 5 | 0 | 100.0% |
| inventory | 4 | 4 | 0 | 100.0% |
| lead_time | 1 | 1 | 0 | 100.0% |
| material | 1 | 1 | 0 | 100.0% |
| min | 1 | 1 | 0 | 100.0% |
| order_by | 1 | 1 | 0 | 100.0% |
| performance | 1 | 1 | 0 | 100.0% |
| purchase | 3 | 3 | 0 | 100.0% |
| region | 1 | 1 | 0 | 100.0% |
| shipping | 1 | 1 | 0 | 100.0% |
| sum | 7 | 7 | 0 | 100.0% |
| supplier | 1 | 1 | 0 | 100.0% |
| top_n | 1 | 1 | 0 | 100.0% |
| transport | 1 | 1 | 0 | 100.0% |
| warehouse | 1 | 1 | 0 | 100.0% |