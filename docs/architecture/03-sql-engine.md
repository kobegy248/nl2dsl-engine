# 03. SQL 引擎设计

## 3.1 标准 SQL 构建

DSL → SQLAlchemy Core 表达式树 → 标准 SQL。

SQLAlchemy Core 提供类型安全的表达式构建，避免 SQL 注入风险。

## 3.2 方言转换

标准 SQL → sqlglot → 目标数据库方言。

支持方言：MySQL、PostgreSQL、ClickHouse、Doris、Presto、Spark。

## 3.3 Query Planner 设计

### 3.3.1 职责

- Join 推导（根据数据血缘自动推导 Join 条件）
- 聚合路由（判断是否需要预聚合表）
- 时间范围限制（防止超大范围查询）
- 查询重写（如 COUNT(DISTINCT x) → 近似计算）

### 3.3.2 优化规则

| 规则 | 说明 |
|------|------|
| 谓词下推 | 将 filter 尽量下推到数据源 |
| 投影下推 | 只 SELECT 需要的字段 |
| 聚合重写 | 命中预聚合表时替换基础表 |
| LIMIT 下推 | 尽早截断数据 |
