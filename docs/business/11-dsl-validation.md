# 11. DSL 校验与风险控制

## 11.1 Schema 校验

- metric 是否在 `metrics.yaml` 中注册
- dimension 是否在 `dimensions.yaml` 中注册
- operator 是否合法
- filter 字段类型是否匹配
- data_source 是否存在
- post_process 引用的指标是否在 metrics 输出中
- group_top_n 的 group_by 是否在 dimensions 输出中
- proportion 是否包含至少一个分组维度
- post_process 输出字段名是否合法

## 11.2 风险控制

| 层级 | 约束项 | 规则 | 超限处理 |
|------|--------|------|---------|
| DSL | SELECT * | 必须指定 dimensions 或 metrics | 校验失败，拒绝执行 |
| DSL | LIMIT | 默认注入 100，最大 `NL2DSL_MAX_LIMIT` | 自动截断 |
| DSL | 时间范围 | 单次查询不超过 1 年 | 校验失败 |
| DSL | 字段白名单 | 只能使用语义层注册的字段 | 校验失败 |
| Planner | Join 数量 | 最多 5 张表 | 校验失败 |
| Planner | 子查询嵌套 | 最多 2 层 | 校验失败 |
| Planner | 聚合复杂度 | 禁止窗口函数 + 嵌套聚合 | 校验失败 |
| PostProcessor | 分组 TopN | `top_n` 为 1-100，分组字段必须已输出 | 校验失败 |
| PostProcessor | 占比 | 分母只能是当前结果集指定指标之和 | 校验失败 |
| SQL | 危险操作 | 禁止 `DELETE`、`UPDATE`、`DROP`、`INSERT` | SQL 扫描拦截 |
| SQL | 注释注入 | 禁止 SQL 注释 `--`、`/* */` | SQL 扫描拦截 |
| SQL | UNION | 禁止 `UNION` / `UNION ALL` | SQL 扫描拦截 |

**SQL 执行前扫描：**

生成最终 SQL 后，通过正则表达式进行最后一道安全检查：

```python
FORBIDDEN_PATTERNS = [
    r"(?i)\b(DELETE|UPDATE|DROP|INSERT|ALTER|CREATE|TRUNCATE)\b",
    r"(?i)/\*.*?\*/",           # /* 注释 */
    r"(?i)--[^\n]*",             # -- 行注释
    r"(?i)\bUNION\s+ALL?\b",   # UNION
    r"(?i);\s*\w+",             # 多语句 (; 后面跟字符)
]
```

匹配到任何危险模式直接拒绝执行。

## 11.3 高级分析治理边界

分组 TopN 和占比不允许由 LLM 生成窗口 SQL、子查询 SQL 或任意计算表达式。

执行流程：

1. LLM 仅生成结构化 `post_process`。
2. DSLValidator 校验指标、维度和参数。
3. SQLBuilder 生成普通分组聚合 SQL。
4. 权限过滤、时间过滤和 SQL 安全扫描正常执行。
5. SQL 执行完成后，PostProcessor 对结果集做受控加工。
6. trace 记录后处理类型、处理前后行数、指标和分组字段。
