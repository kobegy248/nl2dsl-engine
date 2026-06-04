# Semantic Query Optimizer V1 — 实施计划

> 基于 [错误分类体系](semantic-optimizer-error-taxonomy-v2.md) 和 [架构设计](semantic-optimizer-architecture-v2.md) 的分阶段实施计划。

---

## 一、Phase 总览

| Phase | 名称 | 目标 | 规则数 | 预估工期 |
|-------|------|------|--------|---------|
| **P0** | 基础设施 | 搭建 Rule Engine 骨架，跑通首条规则 | 0 | 2-3 天 |
| **P1** | 核心规则 | 确定性修正能力上线（P1 Block + P2 Identity） | 7 | 3-4 天 |
| **P2** | 扩展规则 | 跨组件一致性 + 权限检查（P3 Consistency + P4 Auth） | 6 | 3-4 天 |
| **P3** | 建议规则 | 补全警告 + 歧义检测（P5 Completeness + P6 Ambiguity） | 13 | 4-5 天 |
| **P4** | 评测集成 | 与 Evaluation Framework 对接，量化优化收益 | — | 3-4 天 |
| **P5** | 文档收尾 | 使用指南 + 规则贡献指南 + CLAUDE.md 同步 | — | 1-2 天 |

**总计预估：16-22 天**

---

## 二、P0：基础设施

### 2.1 目标

搭建 Rule Engine 骨架。能加载 1 条 demo 规则 → 调度执行 → 输出 OptimizationReport。

### 2.2 文件清单

```
nl2dsl/optimizer/
├── __init__.py              # 公开 API：optimize() 入口函数
├── normalizer.py            # 结构级规范化（不依赖语义层配置）
├── metadata.py              # RuleMetadata 数据类
├── base.py                  # BaseRule 抽象基类 + RuleResult 数据类
├── context.py               # RuleContext（语义层配置 + 用户信息 + 权限配置）
├── registry.py              # RuleRegistry（装饰器注册 + 查询接口）
├── engine.py                # RuleEngine 入口 + Dispatcher + PriorityQueue + Pipeline
├── report.py                # OptimizationReport 数据类 + 序列化
└── rules/
    ├── __init__.py           # 导出所有规则
    ├── structural.py         # S001-S002
    ├── metric.py             # M001-M004
    ├── dimension.py          # D001-D003
    ├── filter.py             # F001-F005
    ├── intent.py             # I001-I002
    ├── planning.py           # P001-P004
    ├── time.py               # T001-T002
    ├── ambiguity.py          # A001-A002
    └── governance.py         # G001-G002
```

### 2.3 关键接口

```python
# nl2dsl/optimizer/__init__.py

def optimize(
    dsl: dict,
    *,
    semantic_config: SemanticConfig,
    user_id: str | None = None,
    user_role: str | None = None,
    permission_config: PermissionConfig | None = None,
    original_question: str | None = None,
    enabled_rules: list[str] | None = None,      # 白名单模式
    disabled_rules: list[str] | None = None,      # 黑名单模式
) -> tuple[dict, OptimizationReport]:
    """
    对 DSL 执行语义优化。

    返回：
        (优化后的 DSL, OptimizationReport)
    """
    ...
```

### 2.4 里程碑

- [ ] `Normalizer` 通过单元测试（6 种规范化操作）
- [ ] `RuleRegistry` 可注册和查询规则
- [ ] `RuleEngine` 可加载 1 条 demo 规则（S002 Missing DataSource）并输出 Report
- [ ] `OptimizationReport` 可序列化为 JSON
- [ ] `optimize()` 入口函数可端到端调用

### 2.5 不依赖

- CanonicalResolver（P0 用 mock 或跳过规范化层）
- Evaluation Framework（P4 才集成）
- 数据库连接（只依赖 SemanticConfig 和 PermissionConfig 的 dict 表示）

---

## 三、P1：核心规则（P1 Block + P2 Identity）

### 3.1 目标

上线所有**确定性修正**和**结构阻断**规则。这 7 条规则的判定不依赖其他规则的结果。

### 3.2 规则清单

| 优先级 | 错误码 | 规则名称 | 结果 | Confidence | 依赖 |
|--------|--------|---------|------|-----------|------|
| P1 | `S001` | 空查询检测 | Fatal Reject | high | 无 |
| P1 | `S002` | 缺失数据源 | Fatal Reject | high | 无 |
| P1 | `I001` | 未知数据源 | Fatal Reject | high | SemanticConfig.data_sources |
| P2 | `M001` | 聚合函数错误 | Fix | high | SemanticConfig.metrics |
| P2 | `M003` | 缺少别名 | Fix | high | 无 |
| P2 | `D003` | 重复维度 | Fix | high | 无 |
| P2 | `F002` | 操作符类型不匹配 | Fix | high | 字段类型信息 |

### 3.3 每规则测试要求

```python
# 以 M001 为例
class TestFixWrongAggFunc:
    def test_triggers_when_func_differs(self):
        """语义层定义 SUM，DSL 中为 AVG → 触发 M001。"""

    def test_does_not_trigger_when_func_matches(self):
        """语义层定义 SUM，DSL 中为 SUM → 不触发。"""

    def test_fix_replaces_func_correctly(self):
        """触发后 fix() 将 AVG 替换为 SUM。"""

    def test_unregistered_metric_skipped(self):
        """未注册的 metric 不触发 M001（由 M002 处理）。"""

    def test_confidence_is_high(self):
        """确定性匹配 → confidence = high。"""
```

### 3.4 里程碑

- [ ] 7 条规则全部通过单元测试（≥3 个用例/条）
- [ ] P1 Block 规则触发 Fatal Reject 时管道正确终止
- [ ] P2 Identity 规则的 Fix 结果正确更新 DSL
- [ ] 集成测试：1 个 DSL 同时触发 M001 + F002 → 两条规则都执行并修正

---

## 四、P2：扩展规则（P3 Consistency + P4 Auth）

### 4.1 目标

上线**跨组件一致性检查**和**权限阻断**规则。这些规则依赖 P1/P2 的修正结果。

### 4.2 规则清单

| 优先级 | 错误码 | 规则名称 | 结果 | Confidence | 依赖 |
|--------|--------|---------|------|-----------|------|
| P3 | `M004` | 指标-数据源不匹配 | Reject | high | SemanticConfig.data_sources |
| P3 | `I002` | 指标仅在某数据源可用 | Reject / Fix | high/medium | SemanticConfig.data_sources |
| P3 | `D002` | 维度不在数据源中 | Reject | high | SemanticConfig.data_sources |
| P3 | `F001` | 无效枚举值 | Fix | medium | dimension value_map / values |
| P4 | `G001` | 敏感字段访问 | Fatal Reject | high | PermissionConfig.sensitive_fields |
| P4 | `G002` | 指标未授权 | Fatal Reject | high | PermissionConfig.metric_permissions |

### 4.3 F001 模糊匹配算法

```
输入：用户值 "华东区"，候选值列表 ["华东", "华南", "华北", "西南"]

1. 精确匹配 → 直接返回（confidence = high）
2. 前缀匹配（候选值以用户值开头，或反之）→ 返回最佳（confidence = high）
3. 编辑距离 ≤ 1 → 返回最佳（confidence = high）
4. 编辑距离 ≤ 2 → 返回最佳（confidence = medium）
5. 都不满足 → 不修正，Warn（confidence = low）
```

### 4.4 里程碑

- [ ] 6 条规则全部通过单元测试
- [ ] F001 模糊匹配算法测试（精确/前缀/编辑距离1/编辑距离2/无匹配）
- [ ] G001/G002 Fatal Reject 测试（权限拒绝场景）
- [ ] G001/G002 Fatal Reject 测试（权限拒绝场景）
- [ ] 集成测试：P2 修正后 P3 再检查的正确顺序

---

## 五、P3：建议规则（P5 Completeness + P6 Ambiguity）

### 5.1 目标

上线**补全警告**和**歧义检测**规则。这些主要是 Warn 和 Reject + Clarify，不做自动修正。

### 5.2 规则清单

| 优先级 | 错误码 | 规则名称 | 结果 | Confidence |
|--------|--------|---------|------|-----------|
| P5 | `M002` | 未注册指标 | Warn | low |
| P5 | `D001` | 未注册维度 | Warn | low |
| P5 | `F003` | 缺少时间范围 | Warn | medium |
| P5 | `F004` | 矛盾过滤条件 | Reject | high |
| P5 | `F005` | 值类型不匹配 | Warn | low |
| P5 | `P001` | 缺少必要 JOIN | Fix / Warn | high/medium |
| P5 | `P002` | 冗余 JOIN | Warn | high |
| P5 | `P003` | Limit 超限 | Fix | high |
| P5 | `P004` | OrderBy 不在输出中 | Warn | medium |
| P5 | `T001` | 无效时间粒度 | Warn | medium |
| P5 | `T002` | 缺少时间上下文 | Reject + Clarify | high |
| P6 | `A001` | 歧义指标 | Reject + Clarify | N/A |
| P6 | `A002` | 歧义维度 | Reject + Clarify | N/A |

### 5.3 P001 JOIN 路径推导

```
输入：metrics=[gmv], dimensions=[product_name], data_source=orders

1. 从 SemanticConfig 获取 gmv 所属表 → orders
2. 从 SemanticConfig 获取 product_name 所属表 → products
3. orders ≠ products → 需要 JOIN
4. 查询 JOIN 路径图：
   - orders → products（通过 product_id）   ← 唯一路径 → Fix
   - 如果存在多条路径 → Warn（列出所有候选）
5. Fix：注入 JOIN {table: products, on_field: product_id, join_type: inner}
```

### 5.4 A001/A002 歧义检测算法

```
输入：用户问题中的术语 "流水"，语义层候选匹配

1. 在 metrics 注册表中做模糊匹配：
   - 名称完全匹配 → 无歧义（1 个候选）
   - 名称包含关系 → 可能歧义
   - description 关键词匹配 → 可能歧义
   - 同义词匹配（需维护同义词表）→ 可能歧义
2. 候选数 ≥ 2 → Reject + clarification_required
3. 候选数 = 1 → 无歧义
4. 候选数 = 0 → 由 M002（未注册指标）处理
```

### 5.5 里程碑

- [ ] 13 条规则全部通过单元测试
- [ ] P001 JOIN 路径推导：唯一路径 / 多路径 / 无路径 三种场景
- [ ] A001/A002 歧义检测：单候选 / 多候选 / 无候选 三种场景
- [ ] T002 时间上下文检测：同比增长 / 环比 / 去年同期 关键词覆盖

---

## 六、P4：评测集成

### 6.1 目标

与 Evaluation Framework 对接，量化 Semantic Query Optimizer 的优化收益。

### 6.2 CLI 扩展

```bash
# 启用 Optimizer
nl2dsl-eval --dataset tests/evaluation/dataset --optimizer on

# 禁用 Optimizer（Baseline）
nl2dsl-eval --dataset tests/evaluation/dataset --optimizer off

# 对比模式：同时运行 ON/OFF，输出对比报告
nl2dsl-eval --dataset tests/evaluation/dataset --compare

# 仅启用特定规则
nl2dsl-eval --dataset tests/evaluation/dataset --optimizer on --rules M001,F001,P003

# 禁用特定规则（A/B 测试）
nl2dsl-eval --dataset tests/evaluation/dataset --optimizer on --disable-rules A001,A002

# 输出规则级别详情
nl2dsl-eval --dataset tests/evaluation/dataset --optimizer on --verbose-optimizer
```

### 6.3 Runner 改造

```python
# nl2dsl/evaluation/runner.py 新增逻辑

def run_benchmark(dataset, *, optimizer: bool = False, compare: bool = False):
    if compare:
        results_baseline = run_all(dataset, optimizer=False)
        results_optimized = run_all(dataset, optimizer=True)
        return ComparisonReport(results_baseline, results_optimized)
    elif optimizer:
        return run_all_with_optimizer(dataset)
    else:
        return run_all_baseline(dataset)
```

### 6.4 新增评测维度

在现有 12 维度的基础上，新增 **Optimization 类别**（仅在 `--optimizer on` 或 `--compare` 模式下激活）：

| 维度 | 权重 | 说明 | 计算方式 |
|------|------|------|---------|
| **规则修正率** | 5% | 触发的规则中成功自动修正的比例 | `fixes_applied / total_rules_triggered` |
| **规则覆盖率** | 3% | 26 条规则中被触发的比例 | `distinct_error_codes_triggered / 26` |
| **优化增益** | 5% | 优化前后的 Overall Score 差值 | `max(0, score_optimized - score_baseline)` |

### 6.5 对比报告示例

```
# NL2DSL Evaluation Report — Optimizer Comparison

## Overall Score
  Baseline:  82.3%
  Optimized: 89.1%
  Delta:     +6.8%  ✓

## By Category
  Category     | Baseline | Optimized | Delta
  Semantic     | 88.5%    | 94.2%     | +5.7%
  Planning     | 75.0%    | 82.1%     | +7.1%
  Execution    | 90.0%    | 90.0%     | 0.0%
  Governance   | 65.0%    | 85.0%     | +20.0%
  Optimization | —        | 91.5%     | NEW

## Optimizer Stats (avg per case)
  Rules Checked:   26
  Rules Triggered:  8.3
  Fixes Applied:    5.1 (Fix Rate: 61.4%)
  Warnings:         2.1
  Rejections:       1.1
  Avg Latency:      11.2 ms

## Top Fixed Errors
  M001 — Wrong Aggregation Function: 12 次
  F001 — Invalid Enum Value:          8 次
  P003 — Limit Exceeds Max:           6 次
  M003 — Missing Alias:               5 次

## False Positive Analysis
  以下 Fix 导致得分下降（需检查规则逻辑）：
  (无)
```

### 6.6 里程碑

- [ ] CLI 新增 `--optimizer` / `--compare` / `--rules` / `--verbose-optimizer` 参数
- [ ] Runner 支持 Baseline vs Optimizer 双路径
- [ ] 报告新增 Optimization 类别 3 个维度
- [ ] 对比报告含 Per Category Delta / Top Fixed Errors / False Positive Analysis
- [ ] CI 集成：GitHub Actions 中运行 `--compare`，Delta < 0 时报错

---

## 七、P5：文档收尾

### 7.1 产出

| 文档 | 路径 | 内容 |
|------|------|------|
| Optimizer 使用指南 | `docs/evaluation/optimizer-guide.md` | 如何启用、解读报告、A/B 测试规则 |
| 规则贡献指南 | `docs/specs/semantic-optimizer-contributing.md` | 如何新增规则、RuleMetadata 填写规范、测试模板 |
| CLAUDE.md 同步 | 项目根目录 | 更新 Task Routing Rules、新增 optimizer 条目 |

### 7.2 里程碑

- [ ] 使用指南覆盖所有 CLI 参数和使用场景
- [ ] 规则贡献指南含可复制的模板代码
- [ ] CLAUDE.md 的 Task Routing Rules 包含 optimizer 相关条目

---

## 八、依赖关系图

```
P0 (基础设施)
  │
  ▼
P1 (核心规则: P1+P2, 7条)
  │
  ├──────► P2 (扩展规则: P3+P4, 7条)
  │           │
  │           ▼
  │        P3 (建议规则: P5+P6, 12条)
  │           │
  └───────────┴──────► P4 (评测集成)
                           │
                           ▼
                        P5 (文档收尾)
```

- **P1 和 P2 可部分并行**：P1 完成后，P2 的规则编写和 P3 的规则编写可由不同人同时进行（不同 Rule Group 之间无代码依赖）
- **P4 依赖 P1-P3 完成**：评测集成需要所有规则就绪才能测出完整的优化增益
- **P5 依赖 P4 完成**：文档中需要引用实际的评测数据

---

## 九、风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| SemanticConfig 加载逻辑与现有代码不一致 | P1-P3 的规则检测结果不准确 | 中 | 复用 `nl2dsl/semantic/` 的配置加载模块，不重复实现 |
| 模糊匹配（F001/A001/A002）误判率高 | Fix 错误的值导致语义更差 | 中 | 严格的编辑距离阈值 + P4 的 False Positive Analysis 持续监控 |
| JOIN 路径推导复杂度超预期 | P001 在 V1 不可用 | 低 | V1 先实现最简单的单路径推导，多路径场景降级为 Warn |
| Optimizer 引入延迟过高 | 影响查询响应时间 | 低 | 纯规则引擎无 LLM 调用，预估 < 20ms；P0 就建立性能基准 |
| 与现有 correct_dsl 节点的交互不清晰 | 重复修正或冲突 | 中 | 明确分工：Optimizer 修正常规错误，correct_dsl 处理规则无法覆盖的语义问题 |

---

## 十、测试策略

### 10.1 单元测试（每 Phase 必须通过）

| Phase | 测试内容 | 最低覆盖率 |
|-------|---------|-----------|
| P0 | Normalizer、RuleRegistry、RuleEngine、Report 序列化 | 90% |
| P1 | 每规则 ≥ 3 用例（触发/不触发/Fix 正确性） | 95% |
| P2 | 同上 + F001 模糊匹配矩阵 | 95% |
| P3 | 同上 + P001 JOIN 推导 / A001 歧义检测 | 90% |
| P4 | CLI 参数解析、Runner 双路径、报告生成 | 85% |

### 10.2 集成测试

- P1 完成后：1 个 DSL 同时触发 M001 + F002 → 两条规则都执行
- P2 完成后：P2 修正 → P3 再检查的顺序正确性
- P3 完成后：完整 6 级 Priority 管道，含 Fatal Reject 终止和 Normal Reject 继续
- P4 完成后：50 个 E2E 用例 Baseline vs Optimizer 对比

### 10.3 回归测试

- 每次新增规则 → 跑全量 Evaluation（`--compare`），确保 Overall Score 不下降
- CI 中配置：`nl2dsl-eval --compare --threshold-delta 0`（Delta < 0 时报错）

---

## 十一、文件结构总览（最终态）

```
nl2dsl/
├── optimizer/                         # 新增模块
│   ├── __init__.py                    # optimize() 入口
│   ├── normalizer.py
│   ├── metadata.py
│   ├── base.py
│   ├── context.py
│   ├── registry.py
│   ├── engine.py
│   ├── report.py
│   └── rules/
│       ├── __init__.py
│       ├── structural.py              # S001-S002
│       ├── metric.py                  # M001-M004
│       ├── dimension.py               # D001-D003
│       ├── filter.py                  # F001-F005
│       ├── intent.py                  # I001-I002
│       ├── planning.py                # P001-P004
│       ├── time.py                    # T001-T002
│       ├── ambiguity.py               # A001-A002
│       └── governance.py              # G001-G002
│
├── evaluation/                        # 已有模块，P4 扩展
│   ├── runner.py                      # 新增：Baseline vs Optimizer 双路径
│   ├── cli.py / v2_cli.py             # 新增：--optimizer --compare 等参数
│   └── report.py / v2_reporter.py     # 新增：Optimization 类别 3 维度
│
tests/
├── unit/
│   └── optimizer/                     # 新增
│       ├── test_normalizer.py
│       ├── test_registry.py
│       ├── test_engine.py
│       └── rules/
│           ├── test_structural.py
│           ├── test_metric.py
│           ├── test_dimension.py
│           ├── test_filter.py
│           ├── test_intent.py
│           ├── test_planning.py
│           ├── test_time.py
│           ├── test_ambiguity.py
│           └── test_governance.py
│
docs/
├── specs/
│   ├── semantic-optimizer-error-taxonomy-v2.md
│   ├── semantic-optimizer-architecture-v1.md
│   └── semantic-optimizer-implementation-plan-v1.md   # 本文档
└── evaluation/
    └── optimizer-guide.md                              # P5 新增
```
