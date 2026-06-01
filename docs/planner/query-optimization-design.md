# Query Planner 设计

## 设计目标

提供查询优化和路由能力，将 DSL 转换为最高效的执行路径。

> ⚠️ **当前状态**：此模块为预留架构，核心逻辑待实现。当前生产环境通过 `nl2dsl/sql_engine/builder.py` 直接构建 SQL，未经过优化器。

## 架构设计

### QueryOptimizer

职责：对 DSL 进行逻辑优化，生成等效但更高效的 DSL。

预留优化规则：

| 优化规则 | 说明 | 状态 |
|---------|------|------|
| Predicate Pushdown（谓词下推） | 将过滤条件尽可能下推到数据源层 | TODO |
| Projection Pushdown（投影下推） | 只 SELECT 需要的字段 | TODO |
| Join Reordering（Join 重排序） | 按表大小优化 Join 顺序 | TODO |
| Limit Pushdown（Limit 下推） | 将 LIMIT 下推到子查询 | TODO |
| Aggregation Pruning（聚合剪枝） | 消除冗余聚合操作 | TODO |

### QueryRouter

职责：根据 DSL 特征路由到最优执行路径。

预留路由策略：

| 路由目标 | 触发条件 | 状态 |
|---------|---------|------|
| 原始数据表 | 无预聚合可满足 | 默认（当前唯一实现） |
| 预聚合表 | 查询模式命中物化视图 | TODO |
| 缓存层 | 相同查询近期执行过 | TODO |
| 只读副本 | 查询不涉及实时数据 | TODO |

## 与系统的关系

```
LangGraph 管道中的位置：

resolve_semantic（语义解析）
    │
    ▼
[QueryOptimizer.optimize()]  ← 预留优化点
    │
    ▼
[QueryRouter.route()]        ← 预留路由点
    │
    ▼
build_sql（SQL 构建）
```

当前实现中，优化器和路由器为**透传**（直接返回输入），不影响查询正确性。

## 实现计划

当查询量增长出现性能瓶颈时，按以下优先级实现：

1. **P1**：Predicate Pushdown — 对带过滤条件的查询效果最明显
2. **P2**：Projection Pushdown — 减少网络传输量
3. **P3**：Join Reordering — 多表 Join 场景
4. **P4**：Cache Routing — 基于查询指纹的缓存命中
