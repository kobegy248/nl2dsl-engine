# NL2DSL 复杂查询语义理解增强设计

> 日期: 2026-05-31
> 目标: 解决自然语言查询中复合条件、数值范围、否定、时间语义、隐含 JOIN 等复杂场景的理解和转换问题

---

## 1. 背景与问题

当前系统通过 `/query` 端点接收自然语言问题，经 LLM 或 Mock 生成 DSL，再转换为 SQL 执行。实测发现复杂查询存在严重语义丢失：

| 用户问题 | 实际生成的 DSL | 丢失内容 |
|---------|--------------|---------|
| "华东线上**金额大于5000**" | 只有 region + channel | 金额 > 5000 |
| "**非手机**品类且金额>3000" | 只有 category 分组 | 否定 + 数值 |
| "苹果品牌**5000到20000**" | brand + product_name 分组 | 范围过滤 |
| "各品类**最高**的产品" | GROUP BY + ORDER BY | 每组 TOP1 |
| "1月和2月**对比**" | 两个子查询 | 时间过滤 |
| "各**供应商**销售额" | GROUP BY product_name | supplier_dim JOIN |

根因：
- Mock DSL 生成器仅支持关键词匹配，无法处理复合条件
- LLM Prompt 仅 5 个简单示例，无复杂场景覆盖
- SQL Builder 缺失 `between`、`HAVING`、窗口函数等能力

---

## 2. 设计原则

1. **一致性**: 测试环境与生产环境使用同一条 LLM 路径，不维护 Mock 替身
2. **增量改进**: 保留现有架构（StateGraph 节点链路、权限层、RAG、审计等），只改造 DSL 生成和 SQL 构建
3. **向后兼容**: DSL Schema 支持新旧两种 filters 格式（扁平列表 / 条件树）
4. **明确边界**: LLM 负责语义理解（自然语言 → 结构化条件），系统负责执行治理（校验、权限、SQL 构建）

---

## 3. 架构变更

### 3.1 变更前

```
自然语言 → [LLM 路径] 或 [Mock 关键词匹配] → DSL → [SQL Builder] → SQL
             ↓                    ↓
         复杂查询              简单查询 / 测试 / 降级
```

### 3.2 变更后

```
自然语言 → [LLM 唯一路径] → DSL → [语义校验] → [权限注入] → [SQL Builder 扩展] → SQL
             ↓                                              ↓
         零示例 Prompt                                  保留原有
         + JSON Schema                                    行级/列级权限
         + CoT 思维链
```

### 3.3 改动范围

| 模块 | 操作 | 说明 |
|------|------|------|
| `llm/prompts.py` | **重写** | 零示例 + 强规则 + CoT + JSON Schema |
| `llm/client.py` | **增强** | 支持结构化输出（response_format） |
| `dsl/models.py` | **扩展** | Filter 支持条件树；新增 having；time_field/time_range 启用 |
| `dsl/semantic_validator.py` | **新增** | 语义校验：字段存在性、值域、条件冲突 |
| `sql_engine/builder.py` | **扩展** | +between +is_null +条件树 +HAVING |
| `graph/nodes.py` | **简化** | 删除 `_mock_dsl_from_question`；简化 generate_dsl 节点 |
| `graph/nodes.py` | **增强** | `_post_process_dsl` 支持条件树格式 |
| `query/` | **新增** | 结果后处理：每组 TOP1（Python 层） |

### 3.4 删除的代码

| 代码 | 说明 |
|------|------|
| `graph/nodes.py:392-508` `_mock_dsl_from_question()` | 关键词匹配生成器 |
| `graph/nodes.py:191-206` `_extract_top_n()` | 挪到 DSL 后处理层 |
| `graph/nodes.py` Mock 相关分支 | LLM 不可用时的 fallback 逻辑 |

---

## 4. LLM Prompt 设计（零示例策略）

### 4.1 核心设计决策

- **零 few-shot 示例**: 避免 LLM "背诵"示例而非真正理解规则
- **强规则描述**: 用表格详细描述所有 operator、条件树结构、时间格式
- **CoT 思维链**: 强制 LLM 先思考（指标/维度/条件/时间/排序/JOIN/遗漏检查），再输出 JSON
- **JSON Schema 约束**: 结构化输出，严格限制格式

### 4.2 System Prompt 结构

```
1. 角色定义
2. 思维链要求（必须执行的9步检查）
3. 指标映射词典
4. 维度映射词典
5. 过滤条件规则（核心）
   - 12个 operator 的映射表
   - 复合条件树结构（and/or/not）
   - 时间处理规则（最近N天/本周/本月/某年某月）
   - 数值处理规则（大于/小于/之间）
   - 否定处理规则（非/不是/排除）
   - 隐含 JOIN 识别规则
   - HAVING 使用规则
6. 字段格式要求
7. 输出规则
```

### 4.3 JSON Schema 约束

```json
{
  "type": "object",
  "required": ["metrics", "dimensions", "data_source"],
  "properties": {
    "metrics": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["func", "field", "alias"],
        "properties": {
          "func": {"enum": ["sum", "avg", "count", "min", "max"]},
          "field": {"type": "string"},
          "alias": {"type": "string"}
        }
      }
    },
    "dimensions": {"type": "array", "items": {"type": "string"}},
    "filters": {
      "oneOf": [
        {"type": "array", "items": {"$ref": "#/$defs/filter_leaf"}},
        {"$ref": "#/$defs/filter_tree"}
      ]
    },
    "having": {"type": "array", "items": {"$ref": "#/$defs/filter_leaf"}},
    "order_by": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["field", "direction"],
        "properties": {
          "field": {"type": "string"},
          "direction": {"enum": ["asc", "desc"]}
        }
      }
    },
    "limit": {"type": "integer", "minimum": 1, "maximum": 10000},
    "offset": {"type": "integer", "minimum": 0},
    "data_source": {"type": "string"},
    "joins": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["table", "on_field", "join_type", "alias"],
        "properties": {
          "table": {"type": "string"},
          "on_field": {"type": "string"},
          "join_type": {"enum": ["inner", "left", "right"]},
          "alias": {"type": "string"}
        }
      }
    },
    "time_field": {"type": "string"},
    "time_range": {
      "type": "array",
      "items": {"type": "string"},
      "minItems": 2,
      "maxItems": 2
    }
  },
  "$defs": {
    "filter_leaf": {
      "type": "object",
      "required": ["field", "operator"],
      "properties": {
        "field": {"type": "string"},
        "operator": {"enum": ["=", "!=", ">", "<", ">=", "<=", "between", "in", "like", "is_null"]},
        "value": {}
      }
    },
    "filter_tree": {
      "type": "object",
      "required": ["op", "children"],
      "properties": {
        "op": {"enum": ["and", "or", "not"]},
        "children": {
          "type": "array",
          "items": {
            "oneOf": [
              {"$ref": "#/$defs/filter_leaf"},
              {"$ref": "#/$defs/filter_tree"}
            ]
          }
        }
      }
    }
  }
}
```

### 4.4 测试策略

- 测试环境调用真实 LLM（与生产一致）
- `temperature=0` 保证确定性
- 断言检查"关键字段存在"而非精确字符串匹配
- LangSmith 或本地缓存减少重复调用成本

---

## 5. DSL Schema 扩展

### 5.1 Filter 条件树（核心扩展）

向后兼容：支持旧的扁平列表格式，新增条件树格式。

```python
# 旧格式（向后兼容）
{"filters": [
    {"field": "region", "operator": "=", "value": "华东"}
]}

# 新格式：条件树
{"filters": {
    "op": "and",
    "children": [
        {"field": "region", "operator": "=", "value": "华东"},
        {"field": "channel", "operator": "=", "value": "线上"},
        {"field": "pay_amount", "operator": ">", "value": 5000},
        {"op": "not", "children": [
            {"field": "category", "operator": "=", "value": "手机"}
        ]}
    ]
}}
```

### 5.2 新增 having 字段

用于聚合后过滤（如"销售额大于10万的品牌"）。

```python
{"metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
 "dimensions": ["brand"],
 "having": [{"field": "sales_amount", "operator": ">", "value": 100000}]}
```

### 5.3 time_field / time_range 启用

之前存在于 Schema 但 SQL Builder 未使用，本次启用。

```python
{"time_field": "order_date",
 "time_range": ["2026-05-23", "2026-05-30"]}
# 等价于 filters: [{"field": "order_date", "operator": "between", "value": ["2026-05-23", "2026-05-30"]}]
```

---

## 6. SQL Builder 扩展

### 6.1 新增操作符

| 操作符 | 实现 | 说明 |
|--------|------|------|
| `between` | `col.between(v[0], v[1])` | 范围查询 |
| `is_null` | `col.is_(None)` | NULL 检查 |

### 6.2 条件树支持

递归遍历条件树，生成 SQLAlchemy 表达式：

```python
def _build_condition_tree(self, tables, node):
    if node.get("op") == "and":
        return and_(*[self._build_condition_tree(tables, c) for c in node["children"]])
    elif node.get("op") == "or":
        return or_(*[self._build_condition_tree(tables, c) for c in node["children"]])
    elif node.get("op") == "not":
        return not_(self._build_condition_tree(tables, node["children"][0]))
    else:
        # 叶子节点
        return self._build_leaf_condition(tables, node)
```

### 6.3 HAVING 支持

在 `GROUP BY` 之后添加 `HAVING` 子句，过滤聚合后的值：

```python
if dsl.having:
    having_conditions = []
    for h in dsl.having:
        col_ref = text(h.field)  # 引用聚合别名
        if h.operator == ">":
            having_conditions.append(col_ref > h.value)
        # ... 其他操作符
    stmt = stmt.having(and_(*having_conditions))
```

### 6.4 每组 TOP1（Python 层后处理）

"各品类销售额最高的产品"需要在每组内取 TOP1。由于窗口函数改动大，先用 Python 层后处理：

```python
def _extract_top_per_group(data, group_key, order_key, order_desc=True):
    """从已排序数据中每组取第一个."""
    from itertools import groupby
    sorted_data = sorted(
        data,
        key=lambda x: (x.get(group_key), x.get(order_key, 0) * (-1 if order_desc else 1))
    )
    result = []
    for _, group in groupby(sorted_data, key=lambda x: x.get(group_key)):
        result.append(next(group))
    return result
```

**触发条件**: `dimensions` 长度 >= 2 且 `limit == 1` 且 `order_by` 存在。

**后续升级**: 数据量大时，可在 SQL Builder 中实现 `ROW_NUMBER() OVER (PARTITION BY ...)`。

---

## 7. 语义校验层（新增）

在 DSL 生成后、SQL 构建前执行，校验 DSL 的语义正确性。

### 7.1 校验项

| 校验项 | 级别 | 说明 |
|--------|------|------|
| 指标存在性 | error | alias 必须在 registry 中 |
| 维度存在性 | error | name 必须在 registry 中 |
| 数据源存在性 | error | data_source 必须有效 |
| 过滤字段存在性 | warning | 未注册字段给出警告 |
| 数值操作符类型 | error | `>`/`<` 等需要数字值 |
| between 格式 | error | 需要 `[min, max]` 数组 |
| in 格式 | error | 需要列表值 |
| 值域检查 | warning | 值不在已知枚举中 |
| 条件冲突 | error | 如 `A=1 AND A=2` |
| having 无 metric | error | having 必须配合 metric |

### 7.2 错误处理

- **error**: 返回给 LLM 做自动修正（prompt 中注入错误信息，让 LLM 重新生成）
- **warning**: 记录日志，不阻断执行

---

## 8. 删除的代码

| 代码位置 | 内容 | 替代方案 |
|----------|------|---------|
| `graph/nodes.py:392-508` | `_mock_dsl_from_question()` | LLM 唯一路径 |
| `graph/nodes.py:191-206` | `_extract_top_n()` | 保留为 `_post_process_dsl` 的一部分 |
| `graph/nodes.py` | LLM 不可用时走 Mock 的分支 | 返回明确错误 / clarification |
| `graph/nodes.py:209-327` | `_semantic_fix_dsl()` 硬编码部分 | LLM Prompt 内建规则 + 语义校验层 |

---

## 9. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| LLM 输出不稳定 | 测试可能偶发失败 | temperature=0；断言检查关键字段而非精确匹配；结果缓存 |
| LLM 成本增加 | 测试费用上升 | 本地缓存（同 prompt 只调一次）；LangSmith 追踪 |
| 条件树格式解析错误 | 旧数据可能不兼容 | 支持两种格式（扁平列表 / 条件树），自动识别 |
| 复杂查询 LLM 理解仍不准 | 用户体验差 | 语义校验层自动修正；实在不行返回 clarification |

---

## 10. 测试策略

1. **单元测试**: 语义校验器、条件树构建、SQL Builder 扩展
2. **集成测试**: LLM → DSL → 校验 → SQL → 执行的完整链路
3. **E2E 测试**: 22个复杂自然语言查询（复合条件、否定、时间、JOIN、HAVING、占比等）
4. **回归测试**: 原有 253 个 E2E 用例全部通过

---

*设计完成，待审阅。*
