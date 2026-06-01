# 供应链/物流领域 Mock 数据设计

## 领域概述

采购 → 入库 → 仓储 → 出库 → 运输 → 交付 全链路。

## 数据模型

### 事实表

| 表名 | 说明 | 行数 |
|------|------|------|
| purchase_fact | 采购订单事实表 | 200 |
| inventory_fact | 库存事实表 | 150 |
| shipment_fact | 运输事实表 | 180 |

### 维度表

| 表名 | 说明 | 行数 |
|------|------|------|
| supplier_dim | 供应商维度 | 20 |
| material_dim | 物料/商品维度 | 50 |
| warehouse_dim | 仓库维度 | 15 |
| carrier_dim | 承运商维度 | 10 |
| region_dim | 区域维度 | 8 |
| date_dim | 日期维度 | 60 |

## 实体关系

```
purchase_fact ──→ supplier_dim (supplier_id)
            ──→ material_dim (material_id)
            ──→ warehouse_dim (warehouse_id)  [收货仓]
            ──→ region_dim (region_code)      [供应商所在区域]
            ──→ date_dim (date_id)            [订单日期]

inventory_fact ──→ material_dim (material_id)
             ──→ warehouse_dim (warehouse_id)
             ──→ date_dim (date_id)            [库存日期]

shipment_fact ──→ purchase_fact (purchase_id)   [关联采购单]
            ──→ carrier_dim (carrier_id)
            ──→ warehouse_dim (from_warehouse)  [发货仓]
            ──→ warehouse_dim (to_warehouse)    [收货仓]
            ──→ region_dim (from_region)
            ──→ region_dim (to_region)
            ──→ date_dim (ship_date)
```

## 核心指标

| 指标名 | 计算方式 | 说明 |
|--------|---------|------|
| purchase_amount | SUM(order_amount) | 采购金额 |
| purchase_qty | SUM(quantity) | 采购数量 |
| avg_unit_price | AVG(unit_price) | 平均单价 |
| inventory_qty | SUM(stock_quantity) | 库存数量 |
| inventory_amount | SUM(stock_amount) | 库存金额 |
| shipment_qty | SUM(ship_quantity) | 发货数量 |
| shipment_cost | SUM(shipping_cost) | 运输成本 |
| on_time_rate | COUNT(on_time=1)/COUNT(*) | 准时交付率 |
| avg_lead_time | AVG(DATEDIFF(actual_date, order_date)) | 平均交货周期 |
| turnover_days | AVG(days_of_supply) | 库存周转天数 |

## 核心维度

| 维度 | 来源表 | 说明 |
|------|--------|------|
| supplier_name | supplier_dim | 供应商名称 |
| supplier_type | supplier_dim | 供应商类型（原材料/零部件/成品） |
| material_name | material_dim | 物料名称 |
| material_category | material_dim | 物料类别（电子/机械/化工/包装） |
| warehouse_name | warehouse_dim | 仓库名称 |
| warehouse_type | warehouse_dim | 仓库类型（中心仓/区域仓/前置仓） |
| carrier_name | carrier_dim | 承运商名称 |
| transport_mode | shipment_fact | 运输方式（公路/铁路/航空/海运） |
| region_name | region_dim | 区域名称 |
| order_status | purchase_fact | 订单状态（待确认/已发货/在途/已入库/已取消） |
| delivery_status | shipment_fact | 配送状态（待发货/运输中/已签收/异常） |

## 复杂查询场景

1. **多表 JOIN**: 各供应商各物料类别的采购金额
2. **时间窗口**: 最近30天各仓库的入库量
3. **状态流转**: 运输中的订单，按承运商统计
4. **地理分析**: 华东到华南的运输成本对比
5. **复合条件**: 电子类物料、交货周期超过7天、金额大于5万的订单
6. **占比**: 各运输方式的采购金额占比
7. **异常分析**: 配送异常的订单，按供应商和物料分析
8. **库存预警**: 周转天数超过30天的物料

## 权限设计

| 用户 | 租户 | 可见区域 | 可见仓库 |
|------|------|---------|---------|
| sc001 | t001 | 华东、华南 | 上海中心仓、广州区域仓 |
| sc002 | t001 | 华北、西南 | 北京中心仓、成都区域仓 |
| sc003 | t002 | 全部 | 全部 |
