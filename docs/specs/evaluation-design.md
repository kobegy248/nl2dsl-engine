# NL2DSL Evaluation Framework 设计说明

## 一、设计目标

把模糊的"准不准"问题变成可量化的数学题。

传统做法：人工抽查 10 个查询，凭感觉说"还行"。
本框架：自动跑 50+ 个用例，输出 **4 大类 12 维度** 的准确率，精确到小数点后一位。

## 二、核心思路：分层分类打分

别人问你"查华东销售额准不准"——这是模糊问题。

系统把它拆成 4 个类别、12 个独立维度：

```
NL → DSL 的准确性
│
├── Semantic Score (56%)     ← 语义理解
│   ├── Intent        (8%)   ← data_source 选对了吗
│   ├── Metric        (20%)  ← 指标（函数/字段/别名）对吗
│   ├── Dimension     (12%)  ← 分组维度对吗
│   └── Filter        (16%)  ← 过滤条件对吗
│
├── Planning Score (14%)     ← 查询规划
│   ├── Join          (7%)   ← 表关联对吗
│   ├── Limit         (4%)   ← 返回条数限制对吗
│   └── OrderBy       (3%)   ← 排序对吗
│
├── Execution Score (20%)    ← 执行落地
│   ├── SQL Success   (10%)  ← SQL 能跑通吗
│   └── Result Accuracy (10%)← 跑出来的数据对吗
│
└── Governance Score (10%)   ← 安全合规
    ├── Permission    (4%)   ← 越权了吗
    ├── Masking       (3%)   ← 敏感数据脱敏了吗
    └── Audit         (3%)   ← 操作被审计了吗
```

### 权重分配逻辑

| 维度 | 权重 | 类别 | 理由 |
|------|------|------|------|
| Metric | 20% | Semantic | 查询核心内容，错了结果完全不对 |
| Filter | 16% | Semantic | 条件错了数据范围就错了 |
| Dimension | 12% | Semantic | 分组字段错了统计口径就变了 |
| Intent | 8% | Semantic | data_source 选错通常致命，但本身是二元判断 |
| SQL Success | 10% | Execution | 兜底维度，保证最终能跑出数据 |
| Result Accuracy | 10% | Execution | SQL 能跑通不代表结果对，需要数据校验 |
| Join | 7% | Planning | 跨表查询才涉及，不是每个查询都有 |
| Limit | 4% | Planning | topN 数量错了会影响结果 |
| OrderBy | 3% | Planning | 影响 topN 结果，大部分查询不涉及 |
| Permission | 4% | Governance | 企业级场景必备：防止数据泄露 |
| Masking | 3% | Governance | 敏感字段必须脱敏 |
| Audit | 3% | Governance | 操作可追溯 |

## 三、评分算法详解

### 3.1 Intent — 数据源匹配

```python
def score_intent(expected, actual):
    return 1.0 if expected.data_source == actual.data_source else 0.0
```

精确匹配。data_source 选错意味着查询跑在完全错误的表上，一票否决。

### 3.2 Metric — 指标匹配

```python
def score_metrics(expected_list, actual_list):
    for em in expected_list:
        best = max(
            0.4 * (em.func == am.func) +    # 聚合函数
            0.4 * (em.field == am.field) +   # 字段名
            0.2 * (em.alias == am.alias)     # 别名
            for am in actual_list
        )
    # 额外惩罚：多出来的指标每个扣 0.1
```

**设计意图**：允许"接近正确"。
- SUM(pay_amount) alias=sales_amount → 全对，1.0 分
- SUM(pay_amount) alias=revenue → 函数和字段都对，别名错了，0.8 分
- COUNT(id) alias=order_count → 完全错了，0 分

### 3.3 Dimension — 维度匹配（Jaccard）

```python
def score_dimensions(expected, actual):
    intersection = set(expected) & set(actual)
    union = set(expected) | set(actual)
    return len(intersection) / len(union)
```

### 3.4 Filter — 过滤条件匹配

```python
def score_filters(expected_list, actual_list):
    for ef in expected_list:
        best = max(
            0.4 * (ef.field == af.field) +      # 字段
            0.3 * (ef.operator == af.operator) + # 操作符
            0.3 * values_equal(ef.value, af.value)  # 值
            for af in actual_list
        )
```

### 3.5 Join — 关联表匹配

```python
def score_joins(expected_list, actual_list):
    for ej in expected_list:
        best = max(
            0.4 * (ej.table == aj.table) +
            0.3 * (ej.on_field == aj.on_field) +
            0.2 * (ej.join_type == aj.join_type) +
            0.1 * (ej.alias == aj.alias)   # alias 是 bonus
            for aj in actual_list
        )
```

### 3.6 Limit — 条数限制匹配（新增）

```python
def score_limit(expected, actual):
    # None defaults to 100 (DSL default)
    e_val = expected if expected is not None else 100
    a_val = actual if actual is not None else 100
    return 1.0 if e_val == a_val else 0.0
```

**设计意图**：精确匹配。"Top 5" 和 "Top 10" 结果完全不同。

### 3.7 OrderBy — 排序匹配

```python
def score_order_by(expected_list, actual_list):
    # 序列感知：按顺序逐个匹配
    for i in range(max_len):
        if field_match: score += 0.6
        if direction_match: score += 0.4
    # 缺失/额外的条目每个扣 0.2
```

### 3.8 SQL Success — SQL 执行成功

```python
def score_sql_success(sql, error):
    return 1.0 if sql and not error else 0.0
```

### 3.9 Result Accuracy — 结果数据准确性（新增）

```python
def score_result_accuracy(expected_data, actual_data):
    # 对比列名（Jaccard）30% + 对比行数据 70%
    col_jaccard = len(expected_cols & actual_cols) / len(expected_cols | actual_cols)
    row_score = len(expected_rows & actual_rows) / max(len(expected_rows), len(actual_rows))
    return col_jaccard * 0.3 + row_score * 0.7
```

**设计意图**：SQL 能跑通不代表结果对。例如 "华东销售额" 生成了 "华南销售额" 的 SQL，语法正确但结果完全错误。

### 3.10 Permission — 权限检查（新增）

```python
def score_permission(governance_info, expected_dsl):
    sensitive = governance_info.sensitive_fields_accessed
    if not sensitive:
        return 1.0  # 不涉及敏感字段
    if governance_info.permission_error:
        return 1.0  # 敏感字段被正确拦截
    return 0.0      # 敏感字段被泄露
```

**设计意图**：企业级必备。如果查询涉及敏感字段（如手机号、薪资），但系统没有拦截，那就是安全漏洞。

### 3.11 Masking — 数据脱敏（新增）

```python
def score_masking(governance_info, actual_data):
    if not governance_info.sensitive_fields_accessed:
        return 1.0
    # 检查所有敏感字段是否都被正确脱敏
    sensitive = set(governance_info.sensitive_fields_accessed)
    masked = set(governance_info.masked_fields.keys())
    return len(sensitive & masked) / len(sensitive)
```

**设计意图**：敏感字段返回前必须脱敏。例如手机号应显示为 `138****8888`。

### 3.12 Audit — 审计日志（新增）

```python
def score_audit(governance_info):
    return 1.0 if governance_info.audit_logged else 0.0
```

**设计意图**：每次查询操作都应该被记录到审计日志中，便于事后追溯。

## 四、类别得分（Category Scores）

每个类别内部计算加权得分，用于宏观汇报：

| 类别 | 公式 |
|------|------|
| Semantic | (intent×8 + metric×20 + dimension×12 + filter×16) / 56 |
| Planning | (join×7 + limit×4 + order_by×3) / 14 |
| Execution | (sql_success×10 + result_accuracy×10) / 20 |
| Governance | (permission×4 + masking×3 + audit×3) / 10 |

**报告输出示例**：
```
Overall: 82.3%
├── Semantic:   88.5% (Intent 100% | Metric 85% | Dimension 90% | Filter 82%)
├── Planning:   75.0% (Join 80% | Limit 60% | OrderBy 100%)
├── Execution:  90.0% (SQL Success 100% | Result Accuracy 80%)
└── Governance: 65.0% (Permission 80% | Masking 50% | Audit 60%)
```

## 五、数据集设计

```
tests/evaluation/dataset/
├── ecommerce/
│   ├── basic.yaml      (10 cases)  # 简单聚合、分组、过滤
│   ├── filters.yaml    (8 cases)   # =, !=, >, like, in, 多条件组合
│   ├── joins.yaml      (6 cases)   # 单表 JOIN、多表 JOIN、JOIN + 过滤
│   └── multi_dim.yaml  (6 cases)   # 多维度、多指标、topN + 排序
├── bank/
│   └── basic.yaml      (10 cases)  # 账户、交易、客户、产品
└── supply_chain/
    └── basic.yaml      (10 cases)  # 采购、库存、物流
```

共 50 个用例，覆盖：
- **简单 → 复杂**：从单指标聚合到多 JOIN + 多过滤
- **单域 → 多域**：电商、银行、供应链三个业务场景
- **operator 全覆盖**：=, !=, >, <, >=, <=, like, in

每个用例的 YAML 结构：

```yaml
test_cases:
  - id: ec_basic_001
    query: "查询华东地区的销售额"
    description: "Aggregation with region filter"
    tags: ["aggregation", "filter", "basic"]
    expected_dsl:
      data_source: orders
      metrics:
        - func: sum
          field: pay_amount
          alias: sales_amount
      filters:
        - field: region
          operator: "="
          value: 华东
      limit: 10
```

## 六、运行流程

```
1. 加载 YAML 数据集
   └─ DatasetLoader 遍历目录，解析所有 *.yaml 文件
   ↓
2. 对每个用例执行：
   a. POST /api/v1/query（走完整 LangGraph 管道）
   b. 提取 actual_dsl、actual_sql、actual_data
   c. 收集 governance 信息（权限错误、敏感字段、审计记录）
   d. 与 expected_dsl 逐维度对比打分
   ↓
3. 聚合统计：
   a. 整体平均分
   b. 按 Category 分组（Semantic / Planning / Execution / Governance）
   c. 按 domain 分组（ecommerce / bank / supply_chain）
   d. 按 tag 分组（filter / join / aggregation...）
   e. 列出失败用例及原因
   ↓
4. 输出报告
   ├─ JSON：结构化数据，供 CI/CD 消费
   └─ Markdown：人类可读，含 Category 汇总 + ASCII 图表
```

## 七、与端到端测试的区别

| | 端到端测试 | Evaluation Framework |
|--|-----------|---------------------|
| **目的** | 验证"能不能跑通" | 验证"跑得有多准 + 是否合规" |
| **结果** | pass / fail | 0~1 的连续得分 |
| **粒度** | 整体 | 4 大类 12 独立维度 |
| **对比** | 无预期结果 | 有 expected_dsl 作为基准 |
| **治理** | 不测 | 测 Permission/Masking/Audit |
| **用途** | 防止 regression | 指导优化方向 + 合规审计 |

## 八、使用方式

```bash
# 运行完整评测
nl2dsl-eval --dataset tests/evaluation/dataset --output reports/ --format both

# 仅 ecommerce
nl2dsl-eval --dataset tests/evaluation/dataset --domain ecommerce

# 自定义权重（更关注指标准确性）
nl2dsl-eval --weights metric=0.3 filter=0.25

# 启用结果准确性校验（会多调用一次 execute API）
# 在 runner 中设置 check_result_accuracy=True
```

## 九、设计决策回顾

1. **为什么从 7 维度扩展到 12 维度？**
   吸收外部推荐的 4 大类架构，补全了 Governance（权限/脱敏/审计）和 Result Accuracy，同时增加了 Limit 评分。

2. **为什么引入 4 个 Category？**
   12 个平铺维度太多，不适合高层汇报。Category 汇总让报告更清晰：一眼看出是"语义理解"差还是"安全合规"弱。

3. **为什么权重不是平均分配？**
   Metric 和 Filter 是查询的核心内容，错了结果就完全不对；OrderBy 和 Limit 很多查询不涉及，权重过高会稀释整体分数的区分度。Governance 权重较低（10%）是因为不是所有测试用例都涉及敏感数据。

4. **为什么允许部分得分？**
   二元判断太粗糙。alias 写错了但聚合逻辑对 → 仍有 0.8 分，这让优化有方向：先保 func+field 正确，再优化 alias。

5. **Governance 如何落地？**
   - Permission：runner 自动检测 API 是否返回权限错误，对比 sensitive_columns 配置
   - Masking：runner 检查返回数据中敏感字段是否被脱敏
   - Audit：runner 检查审计日志 API 是否有记录
