# NL2DSL V2 评测报告

- 生成时间：2026-06-19T17:10:53.669418
- schema_version：1.0

## 总览

- 用例数：44
- 通过：18 | 失败：26 | 不可用：0
- 整体准确率：81.6%
- 平均延迟：0.0 ms | P50：0.0 ms | P95：0.0 ms

## 各维度

| 维度 | 准确率 |
|------|--------|
| intent | 95.5% |
| metric | 100.0% |
| filter | 81.8% |
| planner | 56.6% |
| governance | 100.0% |

## 按矩阵（generator × optimizer）

| Generator | Optimizer | Total | Passed | Unavailable | Overall |
|-----------|-----------|-------|--------|-------------|---------|
| rule | on | 22 | 9 | 0 | 81.6% |
| rule | off | 22 | 9 | 0 | 81.6% |

## 按 Domain

| Domain | Total | Passed | Failed | Overall |
|--------|-------|--------|--------|---------|
| ecommerce | 44 | 18 | 26 | 81.6% |

## 按 Tag

| Tag | Total | Passed | Failed | Overall |
|-----|-------|--------|--------|---------|
| absolute_year | 2 | 0 | 2 | 77.1% |
| advanced | 6 | 6 | 0 | 82.9% |
| aggregation | 8 | 8 | 0 | 100.0% |
| and | 2 | 0 | 2 | 71.4% |
| between | 2 | 0 | 2 | 71.4% |
| cross_table | 6 | 0 | 6 | 73.8% |
| customer | 4 | 0 | 4 | 75.0% |
| dimension | 2 | 2 | 0 | 100.0% |
| filter | 12 | 4 | 8 | 79.2% |
| greater_than | 2 | 0 | 2 | 71.4% |
| group_top_n | 4 | 4 | 0 | 82.9% |
| having | 2 | 0 | 2 | 61.1% |
| join | 6 | 0 | 6 | 73.8% |
| month | 4 | 0 | 4 | 77.1% |
| multi_condition | 2 | 0 | 2 | 71.4% |
| multi_hop | 2 | 0 | 2 | 71.4% |
| negation | 2 | 2 | 0 | 100.0% |
| not_equal | 2 | 2 | 0 | 100.0% |
| numeric | 6 | 0 | 6 | 71.4% |
| post_process | 6 | 6 | 0 | 82.9% |
| proportion | 2 | 2 | 0 | 82.9% |
| range | 2 | 0 | 2 | 71.4% |
| ranking | 2 | 0 | 2 | 64.3% |
| recent_days | 2 | 0 | 2 | 77.1% |
| region | 2 | 2 | 0 | 100.0% |
| relative | 6 | 0 | 6 | 77.1% |
| standalone_month | 2 | 0 | 2 | 77.1% |
| supplier | 2 | 0 | 2 | 71.4% |
| time | 10 | 0 | 10 | 77.1% |
| top_n | 2 | 0 | 2 | 64.3% |

## Optimizer 统计

- 平均 Fix：0.00
- 平均 Warn：0.14
- 平均 Reject：0.00
- 平均耗时：0.1 ms

## 回归门禁

- 结论：失败 ✗
- Overall delta：+0.0%
- 用例回退 ADV_001：100.0% → 82.9%（降 17.1%）

## 失败用例

| Case ID | Status | Overall | Generator | Optimizer | Query |
|---------|--------|---------|-----------|-----------|-------|
| FILTER_002 | success | 61.1% | rule | off | 销售额大于10万的商品 |
| FILTER_002 | success | 61.1% | rule | on | 销售额大于10万的商品 |
| FILTER_003 | success | 71.4% | rule | off | 价格大于5000的商品 |
| FILTER_003 | success | 71.4% | rule | on | 价格大于5000的商品 |
| FILTER_004 | success | 71.4% | rule | off | 价格在5000到20000之间的商品 |
| FILTER_004 | success | 71.4% | rule | on | 价格在5000到20000之间的商品 |
| FILTER_006 | success | 71.4% | rule | off | 华东地区线上渠道价格大于5000的销售额 |
| FILTER_006 | success | 71.4% | rule | on | 华东地区线上渠道价格大于5000的销售额 |
| JOIN_001 | success | 78.6% | rule | off | 按客户名称统计消费金额 |
| JOIN_001 | success | 78.6% | rule | on | 按客户名称统计消费金额 |
| JOIN_002 | success | 71.4% | rule | off | 按供应商统计销售额 |
| JOIN_002 | success | 71.4% | rule | on | 按供应商统计销售额 |
| JOIN_003 | success | 71.4% | rule | off | 按城市等级统计销售额 |
| JOIN_003 | success | 71.4% | rule | on | 按城市等级统计销售额 |
| RANK_001 | success | 64.3% | rule | off | 销售额最高的10个商品 |
| RANK_001 | success | 64.3% | rule | on | 销售额最高的10个商品 |
| TIME_001 | success | 77.1% | rule | off | 本月销售额 |
| TIME_001 | warning | 77.1% | rule | on | 本月销售额 |
| TIME_002 | success | 77.1% | rule | off | 上月订单量 |
| TIME_002 | warning | 77.1% | rule | on | 上月订单量 |
| TIME_003 | success | 77.1% | rule | off | 最近7天销售额 |
| TIME_003 | warning | 77.1% | rule | on | 最近7天销售额 |
| TIME_004 | success | 77.1% | rule | off | 1月份销售额 |
| TIME_004 | success | 77.1% | rule | on | 1月份销售额 |
| TIME_005 | success | 77.1% | rule | off | 2024年销售额 |
| TIME_005 | success | 77.1% | rule | on | 2024年销售额 |