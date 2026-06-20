# NL2DSL V2 评测报告

- 生成时间：2026-06-20T07:49:19.112982
- schema_version：1.0

## 总览

- 用例数：10
- 通过：5 | 失败：5 | 不可用：0
- 整体准确率：50.0%
- 平均延迟：10.5 ms | P50：7.5 ms | P95：25.2 ms

## 各维度

| 维度 | 准确率 |
|------|--------|
| intent | 50.0% |
| metric | 50.0% |
| filter | 50.0% |
| planner | 50.0% |
| governance | 50.0% |

## 按矩阵（generator × optimizer）

| Generator | Optimizer | Total | Passed | Unavailable | Overall |
|-----------|-----------|-------|--------|-------------|---------|
| rule | off | 10 | 5 | 0 | 50.0% |

## 按 Domain

| Domain | Total | Passed | Failed | Overall |
|--------|-------|--------|--------|---------|
| bank | 10 | 5 | 5 | 50.0% |

## 按 Tag

| Tag | Total | Passed | Failed | Overall |
|-----|-------|--------|--------|---------|
| avg | 1 | 1 | 0 | 100.0% |
| basic | 4 | 3 | 1 | 75.0% |
| channel | 1 | 0 | 1 | 0.0% |
| count | 4 | 2 | 2 | 50.0% |
| customer | 1 | 0 | 1 | 0.0% |
| dimension | 4 | 2 | 2 | 50.0% |
| filter | 1 | 0 | 1 | 0.0% |
| group_by | 1 | 1 | 0 | 100.0% |
| multi_metric | 1 | 0 | 1 | 0.0% |
| order_by | 1 | 0 | 1 | 0.0% |
| product | 1 | 0 | 1 | 0.0% |
| risk | 1 | 1 | 0 | 100.0% |
| sum | 6 | 2 | 4 | 33.3% |
| top_n | 1 | 0 | 1 | 0.0% |
| txn | 1 | 0 | 1 | 0.0% |

## 失败用例

| Case ID | Status | Overall | Generator | Optimizer | Query |
|---------|--------|---------|-----------|-----------|-------|
| bank_004 | error | 0.0% | rule | off | 交易笔数最多的客户 |
| bank_005 | error | 0.0% | rule | off | 存款交易金额合计 |
| bank_006 | error | 0.0% | rule | off | 各产品的持有金额 |
| bank_009 | error | 0.0% | rule | off | 交易笔数和交易金额 |
| bank_010 | error | 0.0% | rule | off | 各渠道的存款金额 |

## 执行错误（评测链路异常，非语义低分）

| Case ID | Generator | Optimizer | Error |
|---------|-----------|-----------|-------|
| bank_004 | rule | off | Column 'org_name' not found in any table |
| bank_005 | rule | off | Column 'org_name' not found in any table |
| bank_006 | rule | off | Column 'org_name' not found in any table |
| bank_009 | rule | off | Column 'org_name' not found in any table |
| bank_010 | rule | off | Column 'org_name' not found in any table |