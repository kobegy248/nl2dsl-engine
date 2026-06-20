# NL2DSL V2 评测报告

- 生成时间：2026-06-20T07:55:59.191702
- schema_version：1.0

## 总览

- 用例数：55
- 通过：42 | 失败：13 | 不可用：0
- 整体准确率：92.6%
- 平均延迟：0.0 ms | P50：0.0 ms | P95：0.0 ms

## 各维度

| 维度 | 准确率 |
|------|--------|
| intent | 98.2% |
| metric | 100.0% |
| filter | 92.7% |
| planner | 82.6% |
| governance | 100.0% |

## 按矩阵（generator × optimizer）

| Generator | Optimizer | Total | Passed | Unavailable | Overall |
|-----------|-----------|-------|--------|-------------|---------|
| rule | off | 55 | 42 | 0 | 92.6% |

## 按 Domain

| Domain | Total | Passed | Failed | Overall |
|--------|-------|--------|--------|---------|
| ecommerce | 55 | 42 | 13 | 92.6% |

## 按 Tag

| Tag | Total | Passed | Failed | Overall |
|-----|-------|--------|--------|---------|
| absolute_year | 1 | 0 | 1 | 77.1% |
| advanced | 3 | 3 | 0 | 82.9% |
| aggregation | 14 | 14 | 0 | 100.0% |
| and | 2 | 1 | 1 | 85.7% |
| avg | 1 | 1 | 0 | 100.0% |
| basic | 10 | 10 | 0 | 100.0% |
| between | 2 | 1 | 1 | 85.7% |
| brand | 3 | 3 | 0 | 100.0% |
| category | 5 | 5 | 0 | 100.0% |
| channel | 4 | 4 | 0 | 100.0% |
| comparison | 1 | 1 | 0 | 100.0% |
| complex | 1 | 1 | 0 | 100.0% |
| count | 2 | 2 | 0 | 100.0% |
| credit | 1 | 1 | 0 | 100.0% |
| cross_table | 3 | 0 | 3 | 73.8% |
| customer | 4 | 2 | 2 | 87.5% |
| customer_type | 4 | 4 | 0 | 100.0% |
| date | 1 | 1 | 0 | 100.0% |
| dimension | 7 | 7 | 0 | 100.0% |
| equal | 1 | 1 | 0 | 100.0% |
| filter | 25 | 21 | 4 | 95.0% |
| gmv | 1 | 1 | 0 | 100.0% |
| greater_equal | 1 | 1 | 0 | 100.0% |
| greater_than | 2 | 1 | 1 | 85.7% |
| group_by | 3 | 3 | 0 | 100.0% |
| group_top_n | 2 | 2 | 0 | 82.9% |
| having | 1 | 0 | 1 | 61.1% |
| in | 2 | 2 | 0 | 100.0% |
| join | 9 | 6 | 3 | 91.3% |
| like | 1 | 1 | 0 | 100.0% |
| month | 2 | 0 | 2 | 77.1% |
| multi_condition | 2 | 1 | 1 | 85.7% |
| multi_dimension | 3 | 3 | 0 | 100.0% |
| multi_filter | 1 | 1 | 0 | 100.0% |
| multi_hop | 1 | 0 | 1 | 71.4% |
| multi_join | 1 | 1 | 0 | 100.0% |
| multi_metric | 3 | 3 | 0 | 100.0% |
| multi_region | 1 | 1 | 0 | 100.0% |
| negation | 1 | 1 | 0 | 100.0% |
| not_equal | 2 | 2 | 0 | 100.0% |
| numeric | 7 | 4 | 3 | 87.8% |
| order_by | 3 | 3 | 0 | 100.0% |
| post_process | 3 | 3 | 0 | 82.9% |
| product_name | 1 | 1 | 0 | 100.0% |
| proportion | 1 | 1 | 0 | 82.9% |
| range | 2 | 1 | 1 | 85.7% |
| ranking | 1 | 0 | 1 | 64.3% |
| recent_days | 1 | 0 | 1 | 77.1% |
| region | 6 | 6 | 0 | 100.0% |
| relative | 3 | 0 | 3 | 77.1% |
| semantic | 1 | 1 | 0 | 100.0% |
| semantic_resolution | 1 | 1 | 0 | 100.0% |
| single_join | 1 | 1 | 0 | 100.0% |
| single_metric | 1 | 1 | 0 | 100.0% |
| standalone_month | 1 | 0 | 1 | 77.1% |
| supplier | 3 | 2 | 1 | 90.5% |
| tier_level | 1 | 1 | 0 | 100.0% |
| time | 5 | 0 | 5 | 77.1% |
| time_filter | 1 | 1 | 0 | 100.0% |
| top_n | 3 | 2 | 1 | 88.1% |
| weekend | 1 | 1 | 0 | 100.0% |

## 失败用例

| Case ID | Status | Overall | Generator | Optimizer | Query |
|---------|--------|---------|-----------|-----------|-------|
| FILTER_002 | success | 61.1% | rule | off | 销售额大于10万的商品 |
| FILTER_003 | success | 71.4% | rule | off | 价格大于5000的商品 |
| FILTER_004 | success | 71.4% | rule | off | 价格在5000到20000之间的商品 |
| FILTER_006 | success | 71.4% | rule | off | 华东地区线上渠道价格大于5000的销售额 |
| JOIN_001 | success | 78.6% | rule | off | 按客户名称统计消费金额 |
| JOIN_002 | success | 71.4% | rule | off | 按供应商统计销售额 |
| JOIN_003 | success | 71.4% | rule | off | 按城市等级统计销售额 |
| RANK_001 | success | 64.3% | rule | off | 销售额最高的10个商品 |
| TIME_001 | success | 77.1% | rule | off | 本月销售额 |
| TIME_002 | success | 77.1% | rule | off | 上月订单量 |
| TIME_003 | success | 77.1% | rule | off | 最近7天销售额 |
| TIME_004 | success | 77.1% | rule | off | 1月份销售额 |
| TIME_005 | success | 77.1% | rule | off | 2024年销售额 |