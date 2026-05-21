# NL2DSL 生产级兜底系统设计

日期: 2026-05-19
范围: Retry Chain + Query Sandbox + Clarification

---

## 一、Retry Chain（LLM 自修复重试）

### 问题
当前 LLM 失败直接 fallback 到 mock DSL，语义完全丢失。

### 方案

```
LLM Generate
  → JSON Parse
    → 失败: 反馈 "JSON 不合法" → Retry (最多3次)
  → Schema Validate
    → 失败: 反馈 "metric 'revenuuee' 不存在，可用: revenue, gmv" → Retry
  → Semantic Validate
    → 失败: 反馈 "dimension 'city' 不在 orders 表中" → Retry
  → 3次都失败 → 返回 Clarification（而非 mock）
```

### 实现

```python
class RetryChain:
    def __init__(self, llm_client, max_retries=3):
        self.llm = llm_client
        self.max_retries = max_retries

    def generate(self, question: str, context: str) -> DSL:
        errors = []
        for attempt in range(self.max_retries):
            prompt = self._build_prompt(question, context, errors)
            raw = self.llm.generate(prompt)
            try:
                dsl_dict = self._parse(raw)
                self._validate(dsl_dict)  # schema + semantic
                return DSL(**dsl_dict)
            except RetryableError as e:
                errors.append(str(e))
                continue
        raise MaxRetryExceeded(errors)

    def _build_prompt(self, question, context, errors):
        base = f"问题: {question}\n上下文: {context}"
        if errors:
            base += f"\n\n之前生成的 DSL 有误:\n" + "\n".join(f"{i+1}. {e}" for i, e in enumerate(errors))
            base += "\n\n请修复上述错误，重新生成正确的 DSL JSON:"
        return base
```

### 关键决策
- **什么错误可以 Retry**: JSON 解析失败、字段不存在、类型错误（LLM 可以修复）
- **什么错误不能 Retry**: 超时、网络错误、权限拒绝（非 LLM 能力范围）
- **Retry prompt 设计**: 必须包含完整的错误 feedback，不能只 say "错了"

---

## 二、Query Sandbox（执行前沙箱预检）

### 问题
当前直接执行生产 SQL，无 cost 预估，可能全表扫描。

### 方案

```
SQL Build
  → Sandbox Execute (LIMIT 10 / EXPLAIN)
    → 检查 scan rows / execution time
      → 超过阈值 → 拒绝，返回风险提示
      → 通过 → Production Execute
```

### 实现

```python
class QuerySandbox:
    def __init__(self, engine, max_scan_rows=100000, max_exec_time_ms=5000):
        self.engine = engine
        self.max_scan_rows = max_scan_rows
        self.max_exec_time_ms = max_exec_time_ms

    def check(self, sql: str) -> SandboxResult:
        # 1. EXPLAIN 检查执行计划
        explain_sql = f"EXPLAIN {sql}"
        plan = self._explain(explain_sql)

        # 2. LIMIT 10 快速执行
        sandbox_sql = self._inject_limit(sql, limit=10)
        start = time.time()
        rows = self._execute(sandbox_sql)
        elapsed = (time.time() - start) * 1000

        # 3. 评估风险
        risks = []
        if plan.estimated_rows > self.max_scan_rows:
            risks.append(f"预估扫描 {plan.estimated_rows} 行，超过阈值 {self.max_scan_rows}")
        if elapsed > self.max_exec_time_ms:
            risks.append(f"执行时间 {elapsed:.0f}ms，超过阈值 {self.max_exec_time_ms}ms")
        if "FULL SCAN" in plan.type:
            risks.append("检测到全表扫描，建议添加索引或过滤条件")

        return SandboxResult(
            passed=len(risks) == 0,
            risks=risks,
            sample_rows=rows,
            estimated_rows=plan.estimated_rows,
        )

    def _inject_limit(self, sql: str, limit: int) -> str:
        # 在 SQL 末尾注入 LIMIT（保留原有 GROUP BY / ORDER BY）
        # 注意：不能简单字符串替换，需要 sqlglot 解析
        pass
```

### 关键决策
- **SQLite 的 EXPLAIN**: SQLite 支持 `EXPLAIN QUERY PLAN`，可以获取 scan 类型和 estimated rows
- **LIMIT 注入**: 用 sqlglot 解析 AST，在 SELECT 级别注入 LIMIT，不能破坏 GROUP BY
- **阈值配置**: scan rows 10万、exec time 5秒，可配置化

---

## 三、Clarification（歧义反问）

### 问题
当前 mock 和 LLM 都直接"硬猜"，不确认歧义。

### 方案

```
User Query
  → Ambiguity Detection
    → 有歧义 → 返回 Clarification Response（反问）
    → 无歧义 → 正常生成 DSL
```

### 歧义检测规则

| 歧义类型 | 检测规则 | 反问示例 |
|---------|---------|---------|
| 时间缺失 | 无 order_date / time_range 过滤 | "请确认时间范围：本月 / 上月 / 全部？" |
| 指标歧义 | "销量"可指订单量/商品数量 | "销量指：1.支付订单量 2.发货数量 3.完成数量？" |
| 维度歧义 | "地区"未指定发货/收货/注册 | "地区指：1.收货地址 2.发货仓库 3.注册地？" |
| 聚合歧义 | "平均客单价"未指定维度 | "按什么维度看：总体 / 渠道 / 品类 / 地区？" |
| 比较基准 | "增长"未指定同比/环比 | "增长指：1.环比上月 2.同比去年？" |

### 实现

```python
class ClarificationDetector:
    def __init__(self, registry: dict):
        self.registry = registry

    def detect(self, question: str, dsl: DSL | None) -> list[ClarificationItem]:
        ambiguities = []

        # 1. 时间缺失检测
        if not dsl or (not dsl.filters or not any(f.field == 'order_date' for f in dsl.filters)):
            if not any(kw in question for kw in ['本月', '上月', '今天', '昨天', '最近', '年', '月', '日']):
                ambiguities.append(ClarificationItem(
                    type='time_missing',
                    question='请确认时间范围',
                    options=['本月', '上月', '最近7天', '全部'],
                ))

        # 2. 指标歧义检测
        ambiguous_metrics = {
            '销量': ['支付订单量', '发货数量', '完成数量'],
            '销售额': ['实付金额', '订单金额', 'GMV'],
        }
        for keyword, options in ambiguous_metrics.items():
            if keyword in question:
                ambiguities.append(ClarificationItem(
                    type='metric_ambiguous',
                    question=f'"{keyword}" 的具体含义',
                    options=options,
                ))

        return ambiguities

class ClarificationItem(BaseModel):
    type: str
    question: str
    options: list[str]
```

### 关键决策
- **检测时机**: 在 DSL 生成之前（避免生成后再修正）和之后（验证 DSL 是否完整）双重检测
- **反问 UI**: API 返回特殊状态 `status: "clarification"`，前端展示选项让用户选择
- **选择后链路**: 用户选择 → 拼接为明确 query → 重新走 DSL 生成

---

## 四、三个模块的集成位置

```
User Query
  ↓
[Clarification Detector] → 有歧义？→ 返回 clarification 响应
  ↓ 无歧义
[Retry Chain]
  → LLM Generate → Validate → 错误？→ Feedback → Retry (3次)
  ↓ 成功
[Schema Validation]
  ↓
[Semantic Resolution]
  ↓
[Permission Injection]
  ↓
[SQL Build]
  ↓
[Query Sandbox] → 高风险？→ 返回 risk 警告
  ↓ 通过
[SQL Scan]
  ↓
[Production Execute]
  ↓
Return Result
```

---

## 五、改动范围

| 文件 | 改动 |
|------|------|
| `nl2dsl/dsl/generator.py` | 新增 `RetryChain` 类 |
| `nl2dsl/query/sandbox.py` | 新增 `QuerySandbox` 类 |
| `nl2dsl/query/clarification.py` | 新增 `ClarificationDetector` 类 |
| `nl2dsl/api_factory.py` | 集成三模块到路由中 |
| `nl2dsl/dsl/models.py` | 新增 `ClarificationResponse` 模型 |
| `tests/e2e/` | 新增三模块的 e2e 测试 |

---

## 六、确认清单

- [ ] Retry Chain: max_retries=3, 错误 feedback 包含具体字段名
- [ ] Sandbox: scan rows 阈值 10万, exec time 阈值 5秒
- [ ] Clarification: 时间缺失 + 指标歧义 + 维度歧义 三种检测
