# NL2DSL 核心机制问答

## 问题 1：怎么保证意图理解不出现偏移，解析出指定的表和字段？

### ① 双层意图识别（LLM + 关键词兜底）

`planner.py:364-391` — LLM 规划失败或给出 `single_query` 时，**强制回退到关键词规则**：

```python
# LLM 说 single_query，但规则识别出 compare → 信规则
if llm_plan.intent == "single_query" and rule_plan.intent != "single_query":
    return rule_plan   # 关键词是 ground truth
```

关键词白名单 (`planner.py:31-44`) 覆盖：对比/比较/同比/环比/vs/趋势/走势/关联/影响...

### ② RAG 增强 Prompt（表结构注入）

`nodes.py:651-654` — 通过 RAG 检索把**真实表结构、指标定义、维度枚举**注入 LLM prompt：

```
【表结构】
- 数据源: orders (对应表 order_fact), 字段: id, product_id...
【可用指标】
- sales_amount: SUM(pay_amount), 销售额
【可用维度】
- product_name, brand, category, region...
```

### ③ 语义解析器（别名 → 真实表/字段）

`semantic/resolver.py:13-48` — LLM 生成的都是**业务别名**，解析时映射为真实数据库对象：

| LLM 输出 | 解析后 |
|---------|--------|
| `metrics: [{alias: "sales_amount"}]` | `field: "SUM(pay_amount)"` |
| `filters: [{field: "region", value: "华东"}]` | `field: "region_code", value: "HD"` |

`value_map` 在 `metrics_test.yaml:58-69` 中配置，如 `"华东": "HD"`。

### ④ DSL 验证器（白名单拦截）

`dsl/validator.py:11-35` — 解析出的表/字段必须在注册表白名单中，否则直接抛错：

```python
if dsl.data_source not in self._data_sources:
    errors.append(f"数据源 '{dsl.data_source}' 不存在")
if m.alias not in self._metrics:
    errors.append(f"指标 '{m.alias}' 不存在")
```

---

## 问题 2：模型生成的表和字段，有没有后续处理？

**有，五层后处理链：**

### ① `_post_process_dsl` — 格式修复

`nodes.py:330-389` — 修复 LLM 常见格式错误：

| 问题 | 修复 |
|------|------|
| 缺 `data_source` | 默认 `"orders"` |
| `metrics` 是字符串而非数组 | 包装为 `[{alias: str}]` |
| `field` 带 `SUM()` 包装 | 解包为纯字段名 |
| `limit` 为负/字符串/超 100 | 修正为 10 或 100 |
| `operator` 不在白名单 | 修正为 `"="` |
| 缺 `order_by` | 自动按第一个 metric desc |

### ② `_semantic_fix_dsl` — 语义补漏

`nodes.py:209-327` — 从用户问题中**硬编码兜底**补充 LLM 漏掉的过滤条件：

```python
if "华东" in question and "region" not in existing_fields:
    filters.append({"field": "region", "operator": "=", "value": "华东"})
# 同理：华南/华北/线上/线下/VIP/新客/老客/top-N 等
```

**Agentic 路径**（有 LLM 时）：让 LLM 自己分析问句中遗漏的过滤条件。

### ③ `_make_correct_dsl_node` — 验证失败自动纠错

`nodes.py:702-827` — 三层纠错：

1. **决策**：LLM 读错误信息，输出检索关键词
2. **检索**：用关键词查 RAG 补充业务知识
3. **再生**：带着 error + 补充知识重新生成 DSL

### ④ SemanticResolver — 别名转正

前面讲过，指标别名 → SQL 表达式，维度值 → 编码值。

### ⑤ 验证子图循环

`graph/subgraphs.py:78-178` — `generate_dsl → validate_dsl → [失败] → correct_dsl → validate_dsl`，最多重试 3 次：

```python
if len(generation_attempts) >= max_retries:  # max_retries = 3
    return "error"
return "retry"  # 进入 correct_dsl
```

---

## 问题 3：怎么判断生成的结果就是想要的？结果如何检验？

**六层检验链：**

```
generate_dsl
    ↓
① validate_dsl    ← 白名单校验（指标/维度/数据源是否存在）
    ↓
② confidence      ← LLM 评估 DSL 质量（0-1 分数）
    │   ├─ syntax:   验证器通过=1.0 / 失败=0.0
    │   ├─ semantic: LLM 判断 DSL 是否回答了用户问题
    │   └─ history:   MVP 固定 1.0
    │   路由: ≥0.8 continue / 0.6-0.8 warning / <0.6 clarify
    ↓
③ build_sql
    ↓
④ scan_sql        ← 安全扫描（禁止 DELETE/DROP/UNION/注释/多语句）
    ↓
⑤ sandbox_check   ← EXPLAIN + LIMIT 10 预览
    │   ├─ 预估扫描 > 10万行 → 风险
    │   ├─ 预览执行 > 5秒 → 风险
    │   └─ 缺少 WHERE → 风险
    │   有风险 → 人工审核 / 无风险 → 执行
    ↓
⑥ execute_sql
    ↓
⑦ verify_dsl      ← 执行后 LLM 自检（PASS/WARN/FAIL）
    │   判断：指标是否匹配？维度是否匹配？过滤是否完整？
    │   目前只警告不阻断，未来可路由回 correct_dsl
    ↓
⑧ audit 日志      ← 完整 trace 可追溯
```

### 关键检验点代码位置：

| 检验层 | 文件 | 核心逻辑 |
|--------|------|---------|
| 白名单校验 | `dsl/validator.py:11-35` | metrics/dimensions/data_sources ∈ registry |
| 质量评分 | `agent/confidence.py:28-91` | syntax(1.0/0) × semantic(0-1) × history(1.0) |
| SQL 安全 | `sql_engine/scanner.py:8-19` | 正则拦截 DELETE/DROP/UNION/注释 |
| 沙箱预览 | `query/sandbox.py:45-83` | EXPLAIN + LIMIT 10 + 耗时检测 |
| 执行后自检 | `graph/nodes.py:947-1041` | LLM 判断 PASS/WARN/FAIL |
| 审计追溯 | `audit/logger.py` | query_id + dsl + sql + trace 全链路 |

---

## 一句话总结

> 意图理解靠"LLM+关键词"双层兜底，字段解析靠"语义解析器+白名单验证"双重约束，结果质量靠"生成前评分→执行前沙箱→执行后自检"三层保险。
