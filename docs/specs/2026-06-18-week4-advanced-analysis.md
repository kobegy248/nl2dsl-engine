# 第四周高级分析语义实施说明

> 日期：2026-06-18
> 范围：分组 TopN、占比、Agent 聚合、评测与链路追踪。

## 1. 设计结论

高级分析继续遵守 DSL First：

- LLM 不生成窗口 SQL、子查询 SQL 或派生计算表达式。
- DSL 使用结构化 `post_process` 描述高级分析意图。
- SQLBuilder 只生成普通、可扫描、可治理的基础聚合 SQL。
- PostProcessor 在 SQL 执行后进行受控计算。

该设计避免扩大 SQL 攻击面，也保留权限、时间过滤、审计和解释能力。

## 2. DSL 扩展

### 分组 TopN

```json
{
  "type": "group_top_n",
  "metric": "sales_amount",
  "group_by": ["category"],
  "top_n": 1,
  "direction": "desc"
}
```

### 占比

```json
{
  "type": "proportion",
  "metric": "sales_amount",
  "output_field": "sales_amount_proportion"
}
```

## 3. 执行流程

```text
自然语言
  → DSL 生成
  → DSL 校验
  → 权限注入
  → 语义优化
  → 基础聚合 SQL
  → SQL 扫描与沙箱
  → SQL 执行
  → PostProcessor
  → 结果解释与审计
```

分组 TopN 查询不会在 SQL 阶段应用全局 LIMIT，否则会错误地把“每组前 N”变成“全局前 N”。

占比分母定义为当前查询结果集中指定指标的总和。因此租户权限、行级权限、过滤条件和时间范围都会先于占比计算生效。

## 4. 校验规则

- `post_process.metric` 必须是当前 DSL 的指标别名。
- `group_top_n.group_by` 必须是当前 DSL 的输出维度。
- `group_top_n.top_n` 范围为 1-100。
- 分组 TopN 至少需要两个输出维度。
- 占比至少需要一个分组维度。
- `output_field` 必须是合法字段标识符。

## 5. 可观测性

执行 trace 增加：

```json
{
  "post_process": {
    "type": "group_top_n",
    "rows_before": 20,
    "rows_after": 5,
    "metric": "sales_amount",
    "group_by": ["category"]
  }
}
```

## 6. 测试结果

- 高级分析定向与 SQLite 集成测试：106 个通过。
- Evaluation、Optimizer、Graph、Agent、复杂查询回归：357 个通过。
