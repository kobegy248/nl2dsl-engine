# NL2DSL 项目面试题与参考答案

> 面向级别：P6+/P7（高级后端/架构师）
> 考察维度：架构设计、工程深度、问题解决、技术选型

---

## 一、架构设计（4题）

### Q1. 为什么不用 NL2SQL，而要引入 DSL 这一层？

**参考答案：**

NL2SQL 的问题是"直译"——LLM 直接生成 SQL，导致四个不可控：

| 问题 | 说明 |
|------|------|
| **不可校验** | SQL 是自由文本，无法结构化校验字段/指标合法性 |
| **不可控权限** | SQL 生成后再做权限拦截，容易被绕过（如子查询、UNION） |
| **不可解释** | 用户问"为什么查这个表"，系统无法回答 |
| **不可治理** | 不同数据库方言差异大，优化策略无法统一 |

DSL 是"语义契约"——LLM 只生成结构化 DSL（metrics/dimensions/filters），系统在 DSL 层面做：
- **校验**：字段是否在语义层注册、操作符是否匹配数据类型
- **权限注入**：行级/列级权限在 DSL → SQL 转换时注入
- **优化**：谓词下推、投影下推在 DSL 层面规划
- **审计**：DSL 可序列化，完整记录查询意图

**一句话：SQL 是实现细节，DSL 是语义契约。**

---

### Q2. Agent 层和 Graph 层的职责边界是什么？为什么要双层解耦？

**参考答案：**

```
Agent 层（宏观编排）          Graph 层（微观执行）
─────────────────────        ─────────────────────
意图识别 → 任务分解            单查询 DSL → 校验
子查询调度 → 结果聚合          权限注入 → SQL 构建
自然语言解释                  扫描 → 执行 → 审计
```

**解耦原因：**
1. **职责分离**：Agent 负责"查什么"（What），Graph 负责"怎么查"（How）
2. **独立演化**：Agent 的意图识别算法可以迭代，不影响 Graph 的执行稳定性
3. **可测试性**：Graph 每个节点可独立单元测试，Agent 可用 mock Graph 测试编排逻辑
4. **多领域复用**：同一套 Graph 管道可被不同 Agent（ecommerce/bank/supply_chain）复用

---

### Q3. 如果要把系统从单租户扩展到多租户，哪些模块需要改造？

**参考答案：**

| 模块 | 改造点 | 复杂度 |
|------|--------|--------|
| **语义层配置** | 每个租户独立的 metrics.yaml / dimensions.yaml | 中 |
| **向量库** | Milvus 集合按租户隔离，或加 tenant_id 字段过滤 | 低 |
| **权限系统** | permissions.yaml 增加 tenant 维度，RowLevelSecurity 注入 tenant_id | 低 |
| **审计日志** | audit_log 表增加 tenant_id 字段 | 低 |
| **数据库连接** | DomainContext 按租户路由到不同的 DB 实例/Schema | 中 |
| **缓存层** | 语义配置缓存按 tenant 隔离，避免跨租户命中 | 中 |
| **DSL 校验** | 同一指标名在不同租户可能有不同定义，校验器需带租户上下文 | 高 |

**关键设计**：`DomainContext` 已经是"每域独立运行时"，多租户可复用这一抽象——每个租户一个 DomainContext 实例。

---

### Q4. 系统如何保证"LLM 幻觉"不会破坏数据安全？

**参考答案：**

三层防御：

```
Layer 1: DSL 结构约束（Pydantic Schema）
  → LLM 只能生成限定字段，无法自由发明字段名

Layer 2: 语义层校验（SemanticValidator）
  → metrics/dimensions 必须在 YAML 中注册
  → filters 的 field 必须是已注册维度

Layer 3: SQL 扫描（SQLScanner）
  → 正则拦截 DELETE/UPDATE/DROP/UNION/注释注入/多语句
  → 即使 LLM 绕过前两层，SQL 执行前最后一道关卡
```

**关键原则**：安全不依赖 LLM 的"诚实"，而是依赖系统的**结构性约束**。

---

## 二、DSL 与语义层（3题）

### Q5. DSL Schema 中 metrics 和 dimensions 的区别是什么？为什么 filters 的 field 必须是维度名而非指标名？

**参考答案：**

| | Metrics | Dimensions |
|--|---------|------------|
| **语义** | 被聚合的值（What to measure） | 分组/筛选依据（How to slice） |
| **SQL 映射** | SELECT 中的聚合表达式 | GROUP BY / WHERE 中的字段 |
| **示例** | `SUM(order_amount)` | `region_code`, `channel_code` |

**filters.field 必须是维度名**的原因：
- 指标是聚合结果，无法直接用于 WHERE 子句（除非用 HAVING）
- 维度是原始字段，可直接用于 WHERE / GROUP BY
- 如果允许指标名出现在 filters 中，SQL 构建时会出现 `WHERE SUM(order_amount) > 100` 的语法错误
- 语义层强制这一约束，避免 LLM 混淆概念

---

### Q6. SemanticResolver 的作用是什么？它在 pipeline 的哪个阶段执行？

**参考答案：**

SemanticResolver 负责**语义名到物理名的映射**：

```python
# 输入：DSL 中的语义名
dsl.metrics = [{"alias": "sales_amount", "func": "sum", "field": "order_amount"}]
dsl.dimensions = ["region"]

# 输出：替换为物理字段名
dsl.metrics = [{"alias": "sales_amount", "func": "sum", "field": "SUM(orders.order_amount)"}]
dsl.dimensions = ["region_code"]  # 从 YAML 查找 region → region_code
```

**执行时机**：在 Graph 管道的 `resolve_semantic` 节点，位于 `permission_check` 之后、`build_sql` 之前。

**为什么在这个位置？**
- 权限检查需要在语义名层面进行（用户是否有权访问"region"维度）
- SQL 构建需要物理字段名（`region_code` 而非 `region`）
- 所以顺序是：权限检查（语义层）→ 语义解析（语义→物理）→ SQL 构建（物理层）

---

### Q7. 如果业务方要求新增一个"近7天销售额"的指标，需要修改哪些文件？

**参考答案：**

1. **configs/metrics.yaml**：注册新指标
   ```yaml
   sales_amount_7d:
     expr: SUM(CASE WHEN order_date >= date('now', '-7 days') THEN order_amount ELSE 0 END)
     description: 近7天销售额
     data_source: orders
   ```

2. **configs/intents.yaml**（可选）：如果该指标对应特定查询意图

3. **tests/evaluation/dataset/**：添加评测用例验证准确率

4. **docs/**：更新设计文档（CLAUDE.md 中不需要改，但 specs 中相关文档需要更新）

**不需要修改的**：Python 代码（符合"配置驱动"原则）

---

## 三、LangGraph 工作流（3题）

### Q8. 画出当前查询管道的完整节点流程图，并说明每个条件分支的触发条件。

**参考答案：**

```
START → clarification
          │─[ambiguities存在] → END (返回澄清问题)
          └─[continue] → plan
                          │─[intent≠single_query] → END (AgentOrchestrator处理)
                          └─[continue] → decompose → validation
                                                    → permission_check
                                                    → resolve_semantic
                                                    → optimize_dsl
                                                    │─[status=error] → END
                                                    └─[continue] → confidence
                                                                    │─[confidence<60] → END (澄清)
                                                                    │─[status=error] → END
                                                                    └─[continue] → build_sql
                                                                                    │─[status=error] → END
                                                                                    └─[simple/complex] → scan_sql
                                                                                                        → sandbox_check
                                                                                                        │─[passed] → execute_sql
                                                                                                        │              │─[status=error] → simplify_dsl → build_sql (重试)
                                                                                                        │              └─[success] → verify_dsl → explain → END
                                                                                                        └─[risk] → human_review
                                                                                                                    │─[rejected] → END
                                                                                                                    └─[approved] → execute_sql
```

**关键条件分支**：
- `clarification`：检测到歧义（时间缺失、指标歧义等）
- `plan`：非 single_query 意图（compare/trend/correlation）走 Agent 路径
- `optimize_dsl`：fatal rejection（如安全违规）直接 END
- `confidence`：DSL 质量评分 < 60 触发澄清
- `sandbox_check`：检测到风险（如耗时预估过高）触发人工审核
- `execute_sql`：执行失败时简化 DSL 重试

---

### Q9. validation subgraph 内部是什么结构？为什么 validation 失败后会路由到 correct_dsl 而不是直接报错？

**参考答案：**

```
validation subgraph:
  generate_dsl → validate_dsl
                    │─[valid] → END (返回上级 graph)
                    └─[invalid] → correct_dsl → validate_dsl (循环)
                                      │
                                      └─[重试3次仍失败] → error → END
```

**不自接报错的原因**：
- LLM 生成的 DSL 可能因"业务知识缺失"而失败（如用了不存在的指标别名）
- `correct_dsl` 会提取错误关键词做**定向 RAG 检索**，补充上下文后让 LLM 重新生成
- 这是"自修正"机制：系统主动学习纠错，而非把错误抛给用户
- 3 次重试后仍失败才报错，避免无限循环

---

### Q10. optimize_dsl 节点是在什么背景下接入的？放在 resolve_semantic 之后、confidence 之前的原因是什么？

**参考答案：**

**接入背景**：LLM 生成的 DSL 常有结构性问题（聚合函数错误、字段类型不匹配、limit 超限等），需要在进入 SQL 构建前自动修正。

**位置选择的原因**：

```
permission_check → resolve_semantic → optimize_dsl → confidence → build_sql
```

- **在 resolve_semantic 之后**：optimizer 需要语义解析后的完整 DSL（含物理字段名）
- **在 confidence 之前**：修正后的 DSL 应该被 confidence 评分，修正质量影响置信度
- **在 build_sql 之前**：避免把有问题的 DSL 转成 SQL（SQL 层面的错误更难修复）

**条件路由**：
- `fatal rejection`（如 S001 空查询结构）→ 直接 END，不进入 SQL 构建
- `warning/fix` → 继续到 confidence，记录优化痕迹

---

## 四、Semantic Optimizer（4题）

### Q11. Optimizer 的三层管道是什么？每层职责分别是什么？

**参考答案：**

```
Raw DSL → [Normalizer] → [Rule Engine] → [Canonical Resolver] → Optimized DSL
           (标准化)        (规则执行)        (规范化解析)
```

| 层 | 职责 | 示例 |
|----|------|------|
| **Normalizer** | 结构标准化：默认值注入、类型强制、去重 | `limit: null` → `limit: 100`；空列表 → None |
| **Rule Engine** | 语义规则检查：26 种错误类型，自动修复 | M001: SUM→COUNT；F002: 字符串不能用 `>` |
| **Canonical Resolver** | 规范化解析：别名映射、值映射 | `华东` → `HD`；`sales_amount` → `SUM(order_amount)` |

**设计理由**：分层后每层职责单一，Normalizer 不访问语义配置（纯结构），Rule Engine 只读语义配置（不改结构），Resolver 做最终映射。

---

### Q12. Rule Engine 的优先级队列是如何工作的？为什么要分 P1-P6 六个优先级？

**参考答案：**

```python
queue = {
    P1: [S001_EmptyQuery],           # 结构性问题（最严重）
    P2: [I001_UnknownDataSource],     # 意图层问题
    P3: [M002_UnregisteredMetric, D001_UnregisteredDimension],  # 语义注册问题
    P4: [M001_WrongAggFunc, F002_OperatorTypeMismatch],         # 语义正确性问题
    P5: [P003_LimitExceedsMax, P004_OrderByNotInOutput],        # 规划层问题
    P6: [G001_SensitiveFieldAccess, G002_MetricNotAuthorized],  # 治理层问题
}
```

**优先级设计原则**：
- **先结构后语义**：空查询（S001）直接拒绝，不需要检查其他规则
- **先注册后内容**：未注册指标（M002）先报，再检查聚合函数是否正确（M001）
- **先语义后治理**：治理规则依赖语义解析结果（如知道是哪个数据源的字段才能判断权限）
- **Fatal 可在任何优先级**：S001（P1）和 G001（P6）都可能是 fatal，触发即停止管道

---

### Q13. 如何实现一条新的优化规则？以"指标别名必须是 snake_case"为例。

**参考答案：**

```python
from nl2dsl.optimizer.base import BaseRule, RuleResult
from nl2dsl.optimizer.metadata import RuleMetadata
from nl2dsl.optimizer.registry import RuleRegistry
import re

@RuleRegistry.register
class M005_AliasNotSnakeCase(BaseRule):
    metadata = RuleMetadata(
        error_code="M005",
        category="Metric",
        description="Metric alias should be snake_case",
        priority=4,
        severity="Fix",
        confidence="high",
        auto_fixable=True,
    )

    def check(self, dsl: dict, context) -> RuleResult | None:
        metrics = dsl.get("metrics") or []
        for i, m in enumerate(metrics):
            alias = m.get("alias", "")
            if alias and not re.match(r"^[a-z][a-z0-9_]*$", alias):
                return RuleResult.from_metadata(
                    self.metadata,
                    description=f"Alias '{alias}' is not snake_case",
                    before={"alias": alias},
                    after={"alias": self._to_snake(alias)},
                    location=f"metrics[{i}].alias",
                )
        return None

    def fix(self, dsl: dict, result: RuleResult) -> dict:
        dsl = dict(dsl)
        metrics = list(dsl.get("metrics", []))
        # 根据 result.location 定位并修复
        # ...
        dsl["metrics"] = metrics
        return dsl

    @staticmethod
    def _to_snake(s: str) -> str:
        return re.sub(r"(?<!^)(?=[A-Z])", "_", s).lower().replace(" ", "_")
```

**注册即生效**：`@RuleRegistry.register` 装饰器会自动将规则加入优先级队列，无需修改 Engine 代码。

---

### Q14. Optimizer 接入 Graph 后，如何确保它不会把正确的 DSL"优化坏"？

**参考答案：**

**防御机制**：

1. **RuleResult 的 `applied` 标志**：修复后标记 `applied=True`，如果修复失败（异常）则标记 `applied=False`
2. **修复后的 DSL 重新校验**：Rule Engine 修复后会用 `DSL.model_validate()` 重新验证
3. **非破坏性修复**：Fix  severity 的规则只做"修正"不做"删除"（如改聚合函数、补别名）
4. **Fatal vs Warning 分离**：Reject severity 只报错不修改，Fix severity 才修改
5. **Trace 记录**：每个优化动作都记录到 graph trace 中，可审计

**监控**：
- `fix_rate`：修复率过高可能说明 LLM 生成质量差
- `warning_rate`：警告率过高可能需要调整规则阈值
- `elapsed_ms`：优化耗时监控，避免成为瓶颈

---

## 五、RAG 与向量检索（2题）

### Q15. RAG 分 4 个集合的设计理由是什么？为什么不把所有文本塞进一个集合？

**参考答案：**

| 集合 | 内容 | 检索策略 | 理由 |
|------|------|----------|------|
| **metrics** | 指标定义、expr、description | 关键词匹配（短文本） | 指标名是精确概念，短词匹配更准 |
| **dimensions** | 维度定义、value_map | 关键词匹配（短文本） | 维度取值是枚举，需要精确匹配 |
| **terms** | 业务术语别名映射 | 语义检索（问句→术语） | 用户用自然语言问，需要语义理解 |
| **queries** | 历史查询+DSL 对 | 语义检索（相似问句） | 找"相似问题"的标准解法 |

**不分一个集合的原因**：
- **检索策略不同**：短文本用关键词，长文本用语义
- **召回精度**：metrics 的 "GMV" 和 queries 的 "上个月的 GMV" 如果在一个集合，向量相似度会把 GMV 指标和 queries 中的 GMV 混淆
- **更新频率**：terms 经常新增别名，metrics 相对稳定，独立集合可独立更新
- **混合检索**：查询时 4 集合并行检索，按相关性加权合并结果

---

### Q16. 元数据同步策略是什么？为什么用"启动自检同步"而非实时同步？

**参考答案：**

**同步策略**：
1. **启动时全量同步**：加载 YAML → 提取文本 → Embed → 写入 Milvus（幂等，同名覆盖）
2. **运行时增量同步**：文件 watcher 检测 YAML 变更 → 只变更的条目重新 Embed → 更新向量库
3. **定时校验**：每小时比对 YAML 和向量库的一致性，修复漂移

**不用实时同步的原因**：
- **性能**：Embed 模型（BGE-base-zh-v1.5）推理有延迟，实时同步会阻塞查询
- **一致性**：批量同步比单条同步更稳定，避免中间状态
- **容错**：同步失败不影响查询（可降级到无 RAG 的 prompt）

---

## 六、权限与治理（2题）

### Q17. 行级权限和列级权限分别在哪个阶段注入？为什么不在 SQL 生成后做字符串替换？

**参考答案：**

| 权限类型 | 注入阶段 | 注入方式 |
|----------|----------|----------|
| **行级权限** | `permission_check` 子图（DSL 层面） | `dsl.filters.append({"field": "region", "operator": "in", "value": ["HD", "HN"]})` |
| **列级权限** | `permission_check` 子图（DSL 层面） | `dsl.dimensions` 中移除敏感字段 |
| **数据脱敏** | `SQLBuilder.build()` 阶段 | `CASE WHEN 有权限 THEN 字段 ELSE '***' END` |

**不用 SQL 字符串替换的原因**：
- **注入位置不可控**：字符串替换无法确定 WHERE 子句的上下文，容易破坏 SQL 结构
- **子查询风险**：如果 SQL 有子查询，字符串替换可能只改外层不改内层
- **方言兼容性**：不同数据库的字符串拼接语法不同（MySQL 用 `CONCAT`，PostgreSQL 用 `||`）
- **审计困难**：DSL 层面的注入可完整记录"注入了哪些条件"，SQL 层面替换后无法追溯

---

### Q18. SQLScanner 的扫描规则有哪些？如何防止"提示词注入"绕过扫描？

**参考答案：**

**扫描规则**：
```python
DANGEROUS_PATTERNS = [
    r"\bDELETE\b", r"\bUPDATE\b", r"\bDROP\b",   # 数据修改
    r"\bUNION\b",                                     # 联合注入
    r"/\*.*?\*/", r"--.*?\n",                        # 注释注入
    r";\s*\w+",                                       # 多语句
    r"\bEXEC\b|\bEXECUTE\b",                          # 存储过程执行
]
```

**防提示词注入**：
- **DSL 先行**：LLM 不生成 SQL，只生成 DSL，SQL 由系统构建——攻击者无法直接控制 SQL
- **结构化校验**：DSL 的 metrics/dimensions 必须是注册过的名称，无法注入任意字段
- **参数化查询**：SQLBuilder 使用 SQLAlchemy Core 的参数化表达式，而非字符串拼接
- **白名单**：只允许 `SELECT` 语句，任何非 SELECT 开头直接拒绝

---

## 七、测试与评估（2题）

### Q19. 测试金字塔的三层分别是什么？每层测试什么？

**参考答案：**

```
        ┌─────────────┐
        │   E2E 测试   │  ← 253 个用例，端到端验证完整链路
        │  (tests/e2e) │
        ├─────────────┤
        │  集成测试    │  ← LangGraph 管道、RAG 检索、Agent 编排
        │(tests/integration)│
        ├─────────────┤
        │   单元测试   │  ← DSL 校验、Optimizer 规则、SQLBuilder
        │ (tests/unit) │
        └─────────────┘
```

| 层 | 数量 | 测试重点 | 运行频率 |
|----|------|----------|----------|
| 单元 | ~600 | 单个函数/规则的正确性 | 每次提交 |
| 集成 | ~50 | 模块间交互（Graph 节点、RAG 流程） | 每次 PR |
| E2E | 253 | 完整查询链路（NL → DSL → SQL → 结果） | 每日/发布前 |

**评估框架**：
- V1：`tests/evaluation/` — 按维度评分（intent/metric/filter/planner/governance）
- V2：`tests/evaluation/dataset/v2/` — 更细粒度的预期 DSL 对比

---

### Q20. 如何评估一次架构改动（如新增 optimizer 节点）对整体准确率的影响？

**参考答案：**

**评估流程**：

1. **基线测试**：在改动前运行完整 E2E 测试集，记录准确率
2. **改动后测试**：相同测试集重新运行，对比 diff
3. **维度拆分**：按 intent/metric/filter/planner/governance 分别看影响
4. **案例分析**：对失败的用例逐一分析，判断是"预期行为变化"还是"回归"

**具体实践**：
```bash
# 跑全量评估
python -m nl2dsl.evaluation.cli --dataset tests/evaluation/dataset --output reports/

# 对比报告
# - 新增 passed：优化器修复了之前失败的用例
# - 新增 failed：优化器破坏了之前通过的用例（需修复）
# - 分数不变：优化器对该用例无影响
```

**关键指标**：
- `overall_score`：总体准确率
- `by_domain`：不同领域的表现差异
- `failed_cases`：失败用例清单，用于根因分析

---

## 八、性能与扩展（2题）

### Q21. 系统的查询延迟瓶颈可能在哪些地方？如何优化？

**参考答案：**

| 瓶颈点 | 延迟来源 | 优化策略 |
|--------|----------|----------|
| **LLM 调用** | 300ms-2s（DSL 生成） | ① 缓存常见查询的 DSL；② 使用流式响应；③ 降级到 Mock DSL |
| **RAG 检索** | 50-200ms（向量检索+重排） | ① 预热向量库；② 短文本用关键词检索替代；③ 本地缓存热点结果 |
| **SQL 执行** | 10ms-10s（取决于数据量） | ① 查询沙箱 LIMIT 预览；② 异步执行+超时控制；③ 连接池 |
| **Optimizer** | <1ms（26 条规则） | ① 规则惰性加载；② 跳过无变更的 DSL；③ 异步执行 |

**长尾优化**：
- `decompose` 节点只在复杂查询触发，简单查询无额外延迟
- `confidence` 节点评分失败时直接路由到澄清，不浪费后续计算

---

### Q22. 如果要支持 1000 QPS，系统的瓶颈在哪里？如何横向扩展？

**参考答案：**

**瓶颈分析**：
- **LLM 调用**：1000 QPS × 平均 500ms = 500 个并发 LLM 请求 → 需要 LLM 集群或批处理
- **向量库**：Milvus Lite 是本地文件，无法多进程共享 → 需要切换到 Milvus Server
- **数据库**：SQLite 单文件，写锁竞争 → 需要切换到 PostgreSQL/MySQL 集群

**扩展方案**：
```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   LB/网关    │────→│  API 服务   │────→│  LLM 代理   │
│  (1000 QPS) │     │  (无状态×N) │     │  (队列+缓存)│
└─────────────┘     └──────┬──────┘     └─────────────┘
                           │
              ┌────────────┼────────────┐
              ↓            ↓            ↓
        ┌─────────┐  ┌─────────┐  ┌─────────┐
        │Milvus   │  │PostgreSQL│  │Redis    │
        │Server   │  │(主从)    │  │(DSL缓存)│
        └─────────┘  └─────────┘  └─────────┘
```

**无状态化改造**：
- `DomainContext` 目前每域单例 → 改为请求级别实例（从配置中心加载）
- `Milvus Lite` 本地文件 → `Milvus Server` 远程服务
- `SQLite` 本地文件 → `PostgreSQL` 连接池

---

## 九、开放性问题（2题）

### Q23. 如果让你重新设计这个项目，你会做哪些不同的选择？

**参考答案（示例思路）**：

1. **DSL 标准**：早期统一 DSL Schema 版本（v1/v2 混用导致兼容性问题）
2. **测试策略**：TDD 开发 optimizer——先写评测用例再写规则，避免规则间冲突
3. **多租户**：DomainContext 抽象一开始就考虑 tenant_id，避免后期大规模重构
4. **可观测性**：每个 Graph 节点的输入/输出都结构化日志，便于线上问题定位
5. **LLM 抽象**：抽象 LLMClient 接口更早，支持多模型切换（目前强耦合 OpenAI 格式）

---

### Q24. 描述一个你在这个项目中遇到的最棘手的技术问题，以及你是如何解决的。

**参考答案（示例——optimizer 接入评估问题）**：

**问题**：接入 optimizer 后，V2 评测分数从 77.9% 降到 73.6%。

**根因**：Normalizer 自动注入 `limit=100` 默认值，但 V2 测试用例中 expected 的 limit 为 None，PlannerScorer 严格比较 `None == 100` 得 0 分。

**解决思路**：
1. **定位**：通过 per-dimension 拆分发现 planner 维度下降 21.4%
2. **分析**：对比 before/after DSL，发现 limit 从无值变为 100
3. **决策**：不是简单地去掉默认值，而是讨论"默认值是否应该在评分时忽略"
4. **修复**：调整 Normalizer 策略——只在 DSL 进入 SQL 构建前注入默认值，评分时不影响

**教训**：自动化工具的"便利"（自动默认值）可能破坏下游契约（评分预期）。

---

## 附录：面试考察点速查表

| 级别 | 必考题 | 加分题 |
|------|--------|--------|
| P6 | Q1/Q5/Q8/Q13/Q19 | Q3/Q9/Q15 |
| P7 | Q2/Q4/Q10/Q14/Q17/Q21 | Q11/Q16/Q22/Q23/Q24 |
| P8 | Q3/Q11/Q16/Q22/Q23 | 开放性问题深度 |
