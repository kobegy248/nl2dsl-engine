# Semantic Query Optimizer V1 — 错误分类体系 v2

> 语义错误分类体系。每个错误码精确对应一种语义问题。
> Optimizer 按此分类体系检测 → 判定 → 记录。

---

## 分类概览

| # | Category | 错误码前缀 | 错误类型数 | 对应 Eval 维度 |
|---|----------|-----------|-----------|---------------|
| 1 | 指标类错误 | `M` | 4 | Metric (20%) |
| 2 | 维度类错误 | `D` | 3 | Dimension (12%) |
| 3 | 过滤条件类错误 | `F` | 5 | Filter (16%) |
| 4 | 意图/数据源类错误 | `I` | 2 | Intent (8%) |
| 5 | 查询规划类错误 | `P` | 4 | Join / Limit / OrderBy (14%) |
| 6 | 时间语义类错误 | `T` | 2 | (新维度，后续纳入 Eval) |
| 7 | 歧义类问题 | `A` | 2 | (新维度，后续纳入 Eval) |
| 8 | 治理类错误 | `G` | 2 | Permission / Masking (10%) |
| 9 | 结构类错误 | `S` | 2 | N/A（阻断性错误） |

**总计：9 大类、26 种错误类型。**

---

## 1. 指标类错误 (`M`)

对应 Evaluation Framework 的 **Metric 维度**（权重 20%）。

| 错误码 | 类型 | 描述 | 检测依据 | 结果 | Confidence |
|--------|------|------|---------|------|-----------|
| `M001` | **Wrong Aggregation Function** | LLM 对已注册指标使用了错误的聚合函数。例如 `AVG(sales_amount)`，但语义层定义 `sales_amount = SUM(pay_amount)` | `metrics.yaml` 中的 `expr` 字段 | **Fix** — 自动替换为语义层定义的 `func` | **high** |
| `M002` | **Unregistered Metric** | LLM 发明了语义层未注册的指标。例如 `revenue`，但语义层只有 `sales_amount` 和 `gmv` | `metrics.yaml` 索引 | **Warn** — 提供候选指标列表（按名称相似度排序） | **low** |
| `M003` | **Missing Alias** | 聚合表达式缺少 alias，后续 HAVING / ORDER BY 无法引用。例如 `SUM(pay_amount)` 没有 alias | DSL 字段检查 | **Fix** — 自动补充默认 alias（如 `field → field_alias`） | **high** |
| `M004` | **Metric-DataSource Mismatch** | 指标注册在数据源 A，但 DSL 的 `data_source` 是 B。例如 `order_count` 属于 `orders`，但 DSL 选了 `products` | `data_sources` 配置中的 `metrics` 列表 | **Reject** — 需要修正 data_source 或替换 metric | **high** |

---

## 2. 维度类错误 (`D`)

对应 Evaluation Framework 的 **Dimension 维度**（权重 12%）。

| 错误码 | 类型 | 描述 | 检测依据 | 结果 | Confidence |
|--------|------|------|---------|------|-----------|
| `D001` | **Unregistered Dimension** | LLM 生成了语义层未注册的维度。例如 `product_type`，但语义层只有 `product_name` | `dimensions` 注册表 | **Warn** — 按名称相似度提供候选维度 | **low** |
| `D002` | **Dimension Not In DataSource** | 维度在语义层存在，但不属于当前 `data_source`。例如 `user_level` 属于 `users` 但 data_source 是 `orders` | `data_sources` 配置中的 `dimensions` 列表 | **Reject** — 需要换 data_source、添加 JOIN 或移除该维度 | **high** |
| `D003` | **Redundant Dimension** | 维度列表中有重复项。例如 `["product_name", "product_name"]` | 去重检查 | **Fix** — 去重保留第一个 | **high** |

---

## 3. 过滤条件类错误 (`F`)

对应 Evaluation Framework 的 **Filter 维度**（权重 16%）。

| 错误码 | 类型 | 描述 | 检测依据 | 结果 | Confidence |
|--------|------|------|---------|------|-----------|
| `F001` | **Invalid Enum Value** | 过滤值不在 value_map 中，但存在可模糊匹配的候选项。例如 `region = "华东区"`，value_map 中有 `"华东"` | `dimensions` 中的 `value_map` / `values` 列表 | **Fix** — 模糊匹配替换（编辑距离 ≤ 2 或前缀匹配） | **medium**（编辑距离=1 → high；编辑距离=2 → medium） |
| `F002` | **Operator-Type Mismatch** | 操作符与字段类型不兼容。例如 `age LIKE "%30%"`，但 `age` 是 INTEGER | 字段类型推断 | **Fix** — 替换为兼容操作符（`LIKE` → `=` for numeric） | **high** |
| `F003` | **Missing Time Range** | 查询包含时间语义词汇（"本月""最近""Q1"），但 DSL 的 `time_range` 或 filters 中没有对应的时间条件 | NLP 关键词匹配 + DSL 字段检查 | **Warn** — 标记可能缺失时间过滤 | **medium** |
| `F004` | **Contradictory Filters** | 同一字段出现互斥的过滤条件。例如 `region = "华东" AND region = "华南"`（AND 语义下不可能同时满足） | 同字段多 filter 检测 | **Reject** — 语义矛盾，无法自动判定用户意图，路由到 LLM Corrector 或用户澄清 | **high** |
| `F005` | **Value Type Mismatch** | 过滤值与字段类型不兼容。例如 `order_date = 2024`（应为日期字符串），`amount = "一百"`（应为数字） | 字段类型推断 + 值类型检查 | **Warn** — 标记可疑，可能的隐式条件（如 `2024` 可能表示 `YEAR(order_date) = 2024`） | **low** |

---

## 4. 意图/数据源类错误 (`I`)

对应 Evaluation Framework 的 **Intent 维度**（权重 8%）。

| 错误码 | 类型 | 描述 | 检测依据 | 结果 | Confidence |
|--------|------|------|---------|------|-----------|
| `I001` | **Unknown DataSource** | `data_source` 不存在于语义层配置中 | `data_sources` 注册表 | **Reject** — 阻断执行 | **high** |
| `I002` | **DataSource-Only Metric Available** | 用户问题中的指标只在特定数据源中定义，但 DSL 选了其他数据源。例如问"GMV"但 data_source 选了 `products`，而 `gmv` 只在 `orders` 中 | `data_sources` 中每个 source 的 `metrics` 列表 | **Reject** — 自动修正 `data_source` 为正确值 | **high**（唯一匹配）；**medium**（多源都有同名 metric） |

---

## 5. 查询规划类错误 (`P`)

对应 Evaluation Framework 的 **Planning 维度**（Join 7% / Limit 4% / OrderBy 3%）。

| 错误码 | 类型 | 描述 | 检测依据 | 结果 | Confidence |
|--------|------|------|---------|------|-----------|
| `P001` | **Missing Required JOIN** | Metrics 和 Dimensions 来自不同数据源，DSL 缺少必要的 JOIN | `data_sources` 配置 + JOIN 路径推导 | **Fix** — JOIN 路径唯一时自动注入（含 join_type / on_field）<br>**Warn** — JOIN 路径多于 1 条时提示候选，由 LLM Corrector 决策 | **high**（唯一路径）<br>**medium**（多条路径） |
| `P002` | **Unnecessary JOIN** | DSL 包含的 JOIN 表未被任何 metric 或 dimension 使用 | 引用分析 | **Warn** — 建议移除冗余 JOIN | **high** |
| `P003` | **Limit Exceeds Max** | `limit` 超过 `NL2DSL_MAX_LIMIT`（默认 10000） | 配置项 | **Fix** — 自动截断为最大值 | **high** |
| `P004` | **OrderBy Field Not In Output** | `order_by` 引用的字段不在 metrics（alias）或 dimensions 中 | 引用检查 | **Warn** — 该排序可能无效或需要额外字段 | **medium** |

---

## 6. 时间语义类错误 (`T`)

对应时间智能相关语义错误。当前 Evaluation Framework 未单独设立维度，建议后续纳入。

| 错误码 | 类型 | 描述 | 检测依据 | 结果 | Confidence |
|--------|------|------|---------|------|-----------|
| `T001` | **Invalid Time Grain** | 指标语义与分组粒度冲突。例如 `daily_sales`（日粒度指标）在 `dimensions` 中按 `year` 分组，或 `monthly_gmv` 按 `day` 分组 | 指标命名约定 + 维度粒度推断 | **Warn** — 标记可能的语义冲突，不自动修正 | **medium** |
| `T002` | **Missing Time Context** | 查询包含对比/趋势语义（"同比增长""环比""去年同期"），但 DSL 缺少 `comparison` 或时间基准信息 | NLP 关键词匹配 + DSL 字段检查 | **Reject** — 需要澄清：对比什么基准？什么时间窗口？<br>同时设置 `clarification_required = true` | **high** |

---

## 7. 歧义类问题 (`A`)

**歧义不是错误**，而是需要澄清的语义不确定性。这是 Semantic Query Engine 的核心能力。

当前 Evaluation Framework 未单独设立维度，建议后续纳入。

| 错误码 | 类型 | 描述 | 检测依据 | 结果 | Confidence |
|--------|------|------|---------|------|-----------|
| `A001` | **Ambiguous Metric** | 用户问题中的术语匹配到多个候选指标，无法唯一确定。例如"流水"可匹配 `sales_amount` / `pay_amount` / `gmv` | 指标名称 + description + 同义词模糊匹配 | **Reject** — 设置 `clarification_required = true`，返回候选列表 | N/A（需要用户决策） |
| `A002` | **Ambiguous Dimension** | 用户问题中的术语匹配到多个候选维度，无法唯一确定。例如"区域销售额"可匹配 `region` / `province` / `city` | 维度名称 + description + 同义词模糊匹配 | **Reject** — 设置 `clarification_required = true`，返回候选列表 | N/A（需要用户决策） |

> **注意**：歧义检测不应自动选择候选。即使某个候选的匹配度最高，只要存在 ≥2 个合理的候选，就应该澄清。

---

## 8. 治理类错误 (`G`)

**Governance 是 Optimizer 的一等公民能力**，不应仅在 `permission_check` 阶段处理。

对应 Evaluation Framework 的 **Governance 维度**（Permission 4% / Masking 3% / Audit 3%）。

| 错误码 | 类型 | 描述 | 检测依据 | 结果 | Confidence |
|--------|------|------|---------|------|-----------|
| `G001` | **Sensitive Field Access** | 当前用户角色尝试查询敏感字段（如手机号、身份证号、薪资），且未配置脱敏规则 | `permissions.yaml` 中的 `sensitive_fields` + 用户角色 | **Reject** — 阻断请求，记录审计日志。<br>除非字段有脱敏规则（脱敏后允许返回） | **high** |
| `G002` | **Metric Not Authorized** | 当前用户角色无权访问请求的指标。例如 `sales` 角色查询 `profit`（利润指标仅对管理层开放） | `permissions.yaml` 中的 `metric_permissions` | **Reject** — 阻断请求，返回权限不足提示 | **high** |

> **G001 vs G002 的区别**：
> - G001：字段级安全（敏感数据泄露风险）
> - G002：指标级权限（业务数据访问控制）
>
> 两者都应在 Optimizer 阶段提前阻断，而不是等到 SQL 执行时才报错。

---

## 9. 结构类错误 (`S`)

阻断性结构错误——DSL 本身不完整，无法进入后续处理。

| 错误码 | 类型 | 描述 | 检测依据 | 结果 | Confidence |
|--------|------|------|---------|------|-----------|
| `S001` | **Empty Query** | `metrics` 和 `dimensions` 均为空——等价于 `SELECT *`，违反 DSL 规范（必须指定 metrics 或 dimensions） | DSL Schema 校验 | **Reject** — 阻断执行 | **high** |
| `S002` | **Missing DataSource** | `data_source` 为空或缺失——无法确定查询目标 | DSL Schema 校验 | **Reject** — 阻断执行 | **high** |

---

## 10. Confidence 机制

每个检测结果附带一个 `confidence` 字段，表示 Optimizer 对该判定的确信程度。

| Confidence | 含义 | 典型场景 | 后续行为 |
|-----------|------|---------|---------|
| **high** | 确定性判定，基于精确配置匹配 | M001（聚合函数替换）、F002（操作符替换）、D003（去重） | 可直接执行 Fix / Reject，不需 LLM 复核 |
| **medium** | 较高置信度，基于启发式规则或命名约定 | F001（编辑距离=2 的模糊匹配）、P001（多 JOIN 路径）、T001（时间粒度冲突） | 执行 Fix 但保留 Warn 日志；或路由到 LLM Corrector |
| **low** | 低置信度，基于统计推断或弱信号 | M002（未注册指标猜候选）、F005（值的歧义）、D001（未注册维度猜候选） | 仅 Warn，不自动 Fix，路由到 LLM Corrector 或用户澄清 |

### 10.1 与结果类型的映射

```
Fix   + high   → 自动修正，静默执行
Fix   + medium → 修正并记录日志，供后续审计
Fix   + low    → 不推荐（low confidence 不应自动 Fix）

Warn  + high   → 强警告，几乎确定有问题
Warn  + medium → 中等警告，建议人工/LLM 复核
Warn  + low    → 弱提示，可能不是问题

Reject + high  → 确定性阻断（如权限拒绝、结构缺失）
Reject + medium→ 阻断并建议 LLM Corrector 处理
Reject + low   → 阻断并要求用户澄清（clarification_required）
```

---

## 11. 完整错误码速查表

| 错误码 | 类别 | 简短描述 | 结果 | Confidence |
|--------|------|---------|------|-----------|
| `M001` | 指标 | 聚合函数使用错误 | Fix | high |
| `M002` | 指标 | 未注册的指标 | Warn | low |
| `M003` | 指标 | 缺少别名 | Fix | high |
| `M004` | 指标 | 指标与数据源不匹配 | Reject | high |
| `D001` | 维度 | 未注册的维度 | Warn | low |
| `D002` | 维度 | 维度不在数据源中 | Reject | high |
| `D003` | 维度 | 重复维度 | Fix | high |
| `F001` | 过滤 | 无效枚举值 | Fix | medium |
| `F002` | 过滤 | 操作符与类型不匹配 | Fix | high |
| `F003` | 过滤 | 缺少时间范围 | Warn | medium |
| `F004` | 过滤 | 矛盾过滤条件 | Reject | high |
| `F005` | 过滤 | 值类型不匹配 | Warn | low |
| `I001` | 意图 | 未知数据源 | Reject | high |
| `I002` | 意图 | 指标仅在某数据源可用 | Reject | high/medium |
| `P001` | 规划 | 缺少必要 JOIN | Fix / Warn | high/medium |
| `P002` | 规划 | 冗余 JOIN | Warn | high |
| `P003` | 规划 | Limit 超限 | Fix | high |
| `P004` | 规划 | OrderBy 不在输出中 | Warn | medium |
| `T001` | 时间 | 无效时间粒度 | Warn | medium |
| `T002` | 时间 | 缺少时间上下文 | Reject | high |
| `A001` | 歧义 | 指标歧义 | Reject + Clarify | N/A |
| `A002` | 歧义 | 维度歧义 | Reject + Clarify | N/A |
| `G001` | 治理 | 敏感字段访问 | Reject | high |
| `G002` | 治理 | 指标未授权 | Reject | high |
| `S001` | 结构 | 空查询 | Reject | high |
| `S002` | 结构 | 缺少数据源 | Reject | high |

---

## 12. 统计摘要

| 维度 | 数量 |
|------|------|
| 总类别 | 9 |
| 总错误类型 | 26 |
| Fix | 7 |
| Warn | 7 |
| Reject | 12（含 2 个 Clarify） |
| high confidence | 18 |
| medium confidence | 5 |
| low confidence | 3 |

### 按结果类型分布

```
Fix:    ███████░░░░░░░░░░░░░░░░ 7  (27%)
Warn:   ███████░░░░░░░░░░░░░░░░ 7  (27%)
Reject: ████████████░░░░░░░░░░░░ 12 (46%)
```

### 按 Confidence 分布

```
high:   ██████████████████░░░░░░ 18 (69%)
medium: █████░░░░░░░░░░░░░░░░░░░ 5  (19%)
low:    ███░░░░░░░░░░░░░░░░░░░░░ 3  (12%)
```

---

## 13. 与 Evaluation Framework 的映射关系

| Eval Category | Eval Weight | 对应错误码 | 新增错误码 |
|---------------|------------|-----------|-----------|
| Semantic — Metric | 20% | M001-M004 | — |
| Semantic — Dimension | 12% | D001-D003 | — |
| Semantic — Filter | 16% | F001-F005 | — |
| Semantic — Intent | 8% | I001-I002 | — |
| Planning — Join | 7% | P001-P002 | — |
| Planning — Limit | 4% | P003 | — |
| Planning — OrderBy | 3% | P004 | — |
| Execution — SQL Success | 10% | — | — |
| Execution — Result Accuracy | 10% | — | — |
| Governance — Permission | 4% | G001-G002 | — |
| Governance — Masking | 3% | G001 | — |
| Governance — Audit | 3% | — | — |
| *(New)* Time | *(建议新增)* | — | T001-T002 |
| *(New)* Ambiguity | *(建议新增)* | — | A001-A002 |

> Execution 维度（SQL Success / Result Accuracy）是后置结果，不在 Optimizer 的检测范围内。
> Audit 维度在 Optimizer 阶段无法检测，属于运行时行为。
