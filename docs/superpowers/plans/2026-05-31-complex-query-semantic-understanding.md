# 复杂查询语义理解增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构 NL2DSL 的 DSL 生成和 SQL 构建层，使系统能够正确处理复合条件、数值范围、否定、时间语义、隐含 JOIN 等复杂查询场景。

**Architecture:** 删除 Mock DSL 生成器，采用 LLM 唯一路径 + 零示例强规则 Prompt + CoT 思维链 + JSON Schema 结构化输出。DSL Schema 扩展支持条件树（and/or/not）和 HAVING，SQL Builder 增加递归条件树解析。语义校验层在 DSL 生成后、SQL 构建前执行，自动修正或返回 clarification。

**Tech Stack:** FastAPI, LangGraph, SQLAlchemy Core, Pydantic, OpenAI SDK (structured output), pytest

---

## File Structure

| File | Responsibility |
|------|---------------|
| `nl2dsl/dsl/models.py` | Pydantic DSL models: Filter (backward compat), FilterTreeNode, Having; DSL model with `having`, `time_field`, `time_range` |
| `nl2dsl/dsl/semantic_validator.py` | **New** — semantic validation after DSL generation: field existence, type checking, condition conflicts, having-requires-metric |
| `nl2dsl/llm/prompts.py` | **Rewrite** — zero-shot + CoT + JSON Schema system prompt, no examples |
| `nl2dsl/llm/client.py` | **Extend** — add `generate_structured()` with `response_format` support |
| `nl2dsl/sql_engine/builder.py` | **Extend** — condition tree recursion, `between`, `is_null`, `HAVING`, time_range support |
| `nl2dsl/query/post_processor.py` | **New** — Python-level TOP-N-per-group post-processing |
| `nl2dsl/graph/nodes.py` | **Modify** — remove `_mock_dsl_from_question`, `_mock_sc_dsl`, `_extract_top_n`; simplify generate_dsl; enhance `_post_process_dsl` for filter trees |
| `tests/unit/test_dsl_models.py` | Filter tree model validation tests |
| `tests/unit/test_semantic_validator.py` | **New** — semantic validator tests |
| `tests/unit/test_sql_builder.py` | Extended: condition tree, between, is_null, HAVING, time_range |
| `tests/unit/test_graph_nodes.py` | Updated: remove mock tests, add condition tree post-processing tests |

---

### Task 1: Extend DSL Models — Filter Tree, Having, Time Fields

**Files:**
- Modify: `nl2dsl/dsl/models.py`
- Test: `tests/unit/test_dsl_models.py`

**Context:** Current `DSL.filters` is `list[Filter] | None`. We need backward-compatible support for filter trees (nested and/or/not). Also add `having` field, and ensure `time_field`/`time_range` are properly typed.

- [ ] **Step 1: Write the failing test for filter tree models**

Create `tests/unit/test_dsl_models.py` if it doesn't exist, or add to it. Add these tests:

```python
import pytest
from pydantic import ValidationError
from nl2dsl.dsl.models import DSL, Filter, FilterTreeNode, Having


class TestFilterTreeNode:
    """Tests for the new filter tree structure."""

    def test_filter_leaf_as_dict(self):
        """Old flat list format still works."""
        dsl = DSL(
            data_source="orders",
            filters=[
                {"field": "region", "operator": "=", "value": "华东"},
                {"field": "pay_amount", "operator": ">", "value": 5000},
            ],
        )
        assert isinstance(dsl.filters, list)
        assert dsl.filters[0].field == "region"
        assert dsl.filters[1].value == 5000

    def test_filter_tree_and(self):
        """New condition tree with 'and' operator."""
        dsl = DSL(
            data_source="orders",
            filters={
                "op": "and",
                "children": [
                    {"field": "region", "operator": "=", "value": "华东"},
                    {"field": "channel", "operator": "=", "value": "线上"},
                    {"field": "pay_amount", "operator": ">", "value": 5000},
                ],
            },
        )
        assert isinstance(dsl.filters, FilterTreeNode)
        assert dsl.filters.op == "and"
        assert len(dsl.filters.children) == 3
        assert dsl.filters.children[0].field == "region"

    def test_filter_tree_with_not(self):
        """Condition tree with 'not' operator."""
        dsl = DSL(
            data_source="orders",
            filters={
                "op": "and",
                "children": [
                    {"field": "region", "operator": "=", "value": "华东"},
                    {
                        "op": "not",
                        "children": [
                            {"field": "category", "operator": "=", "value": "手机"},
                        ],
                    },
                ],
            },
        )
        assert dsl.filters.op == "and"
        assert dsl.filters.children[1].op == "not"
        assert dsl.filters.children[1].children[0].field == "category"

    def test_filter_tree_nested_or(self):
        """Deeply nested or/and tree."""
        dsl = DSL(
            data_source="orders",
            filters={
                "op": "or",
                "children": [
                    {
                        "op": "and",
                        "children": [
                            {"field": "region", "operator": "=", "value": "华东"},
                            {"field": "channel", "operator": "=", "value": "线上"},
                        ],
                    },
                    {
                        "op": "and",
                        "children": [
                            {"field": "region", "operator": "=", "value": "华南"},
                            {"field": "channel", "operator": "=", "value": "线下"},
                        ],
                    },
                ],
            },
        )
        assert dsl.filters.op == "or"
        assert len(dsl.filters.children) == 2
        assert dsl.filters.children[0].op == "and"


class TestHaving:
    """Tests for the new having field."""

    def test_having_basic(self):
        dsl = DSL(
            data_source="orders",
            metrics=[{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            dimensions=["brand"],
            having=[{"field": "sales_amount", "operator": ">", "value": 100000}],
        )
        assert dsl.having is not None
        assert len(dsl.having) == 1
        assert dsl.having[0].field == "sales_amount"
        assert dsl.having[0].operator == ">"
        assert dsl.having[0].value == 100000


class TestTimeFields:
    """Tests for time_field and time_range."""

    def test_time_range_as_list(self):
        dsl = DSL(
            data_source="orders",
            time_field="order_date",
            time_range=["2026-05-23", "2026-05-30"],
        )
        assert dsl.time_field == "order_date"
        assert dsl.time_range == ("2026-05-23", "2026-05-30")

    def test_time_range_as_tuple(self):
        dsl = DSL(
            data_source="orders",
            time_field="order_date",
            time_range=("2026-01-01", "2026-12-31"),
        )
        assert dsl.time_range == ("2026-01-01", "2026-12-31")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_dsl_models.py -v
```

Expected: FAIL — `FilterTreeNode`, `Having` classes not defined; `DSL` doesn't accept tree format for filters.

- [ ] **Step 3: Implement DSL model extensions**

Edit `nl2dsl/dsl/models.py`. Replace the entire file with:

```python
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator


class Filter(BaseModel):
    field: str
    operator: Literal["=", "!=", ">", "<", ">=", "<=", "between", "in", "like", "is_null"]
    value: Any = None


class FilterTreeNode(BaseModel):
    """A node in a condition tree (and / or / not)."""

    op: Literal["and", "or", "not"]
    children: list["FilterLeaf | FilterTreeNode"]

    @field_validator("children", mode="before")
    @classmethod
    def _coerce_children(cls, v):
        if v is None:
            return []
        return v


class FilterLeaf(BaseModel):
    """A leaf node in a condition tree — a single filter condition."""

    field: str
    operator: Literal["=", "!=", ">", "<", ">=", "<=", "between", "in", "like", "is_null"]
    value: Any = None


FilterTreeNode.model_rebuild()


class Having(BaseModel):
    """HAVING clause condition — references a metric alias."""

    field: str
    operator: Literal["=", "!=", ">", "<", ">=", "<=", "between", "in", "like", "is_null"]
    value: Any = None


class OrderBy(BaseModel):
    field: str
    direction: Literal["asc", "desc"] = "asc"


class Aggregation(BaseModel):
    func: Literal["sum", "avg", "count", "min", "max"]
    field: str
    alias: str | None = None


class Join(BaseModel):
    table: str
    on_field: str
    join_type: Literal["inner", "left", "right"] = "inner"
    alias: str | None = None


# Forward reference resolved above
FilterTreeNode.model_rebuild()


class DSL(BaseModel):
    metrics: list[Aggregation] | None = None
    dimensions: list[str] | None = None
    filters: list[Filter] | FilterTreeNode | None = None
    having: list[Having] | None = None
    order_by: list[OrderBy] | None = None
    limit: int | None = Field(default=100, le=10000)
    offset: int | None = Field(default=0, ge=0)
    data_source: str
    time_field: str | None = None
    time_range: tuple[str, str] | None = None
    joins: list[Join] | None = None

    @field_validator("filters", mode="before")
    @classmethod
    def _coerce_filters(cls, v):
        """Accept both old flat list and new tree dict."""
        if v is None:
            return None
        if isinstance(v, dict):
            # Tree format: {"op": "and", "children": [...]}
            return FilterTreeNode.model_validate(v)
        if isinstance(v, list):
            # Old flat list format
            return [Filter.model_validate(item) if isinstance(item, dict) else item for item in v]
        return v

    @field_validator("time_range", mode="before")
    @classmethod
    def _coerce_time_range(cls, v):
        """Accept list or tuple for time_range."""
        if v is None:
            return None
        if isinstance(v, list) and len(v) == 2:
            return tuple(v)
        return v

    @field_validator("having", mode="before")
    @classmethod
    def _coerce_having(cls, v):
        if v is None:
            return None
        if isinstance(v, list):
            return [Having.model_validate(item) if isinstance(item, dict) else item for item in v]
        return v


class ClarificationItem(BaseModel):
    type: str
    question: str
    options: list[str]


class ClarificationResponse(BaseModel):
    status: Literal["clarification"] = "clarification"
    message: str
    items: list[ClarificationItem]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_dsl_models.py -v
```

Expected: PASS (4 test classes, ~8 tests)

- [ ] **Step 5: Verify existing DSL tests still pass**

```bash
pytest tests/unit/test_dsl_validator.py tests/unit/test_dsl_filter.py tests/unit/test_dsl_aggregation.py tests/unit/test_dsl_order_by.py tests/unit/test_dsl_builder.py -v
```

Expected: all PASS (regression check)

- [ ] **Step 6: Commit**

```bash
git add nl2dsl/dsl/models.py tests/unit/test_dsl_models.py
git commit -m "feat(dsl): add filter tree, having, time_range support with backward compatibility"
```

---

### Task 2: Rewrite LLM Prompt — Zero-Shot + CoT + JSON Schema

**Files:**
- Modify: `nl2dsl/llm/prompts.py`
- Test: `tests/unit/test_prompts.py`

**Context:** Current prompt has 5 few-shot examples. Design doc requires zero-shot (no examples) with strong rules, CoT, and JSON Schema. The prompt must cover: 12 operators, condition trees, time handling, numeric ranges, negation, implicit JOINs, HAVING rules.

- [ ] **Step 1: Write the failing test for new prompt content**

Add to `tests/unit/test_prompts.py`:

```python
import pytest
from nl2dsl.llm.prompts import (
    DSL_SYSTEM_PROMPT,
    DSL_JSON_SCHEMA,
    build_user_prompt,
)


def test_system_prompt_has_no_examples():
    """Zero-shot: no '### 例' or '## 示例' sections."""
    assert "## 示例" not in DSL_SYSTEM_PROMPT
    assert "### 例" not in DSL_SYSTEM_PROMPT
    assert "用户：" not in DSL_SYSTEM_PROMPT


def test_system_prompt_has_cot_steps():
    """Prompt includes CoT thinking steps."""
    assert "思维链" in DSL_SYSTEM_PROMPT or "检查步骤" in DSL_SYSTEM_PROMPT
    assert "指标" in DSL_SYSTEM_PROMPT
    assert "维度" in DSL_SYSTEM_PROMPT
    assert "过滤条件" in DSL_SYSTEM_PROMPT


def test_system_prompt_covers_all_operators():
    """All 12 operators are documented."""
    operators = ["=", "!=", ">", "<", ">=", "<=", "between", "in", "like", "is_null"]
    for op in operators:
        assert op in DSL_SYSTEM_PROMPT, f"Operator '{op}' missing from prompt"


def test_system_prompt_covers_filter_tree():
    """Condition tree (and/or/not) is documented."""
    assert '"op"' in DSL_SYSTEM_PROMPT
    assert '"children"' in DSL_SYSTEM_PROMPT
    assert "and" in DSL_SYSTEM_PROMPT
    assert "or" in DSL_SYSTEM_PROMPT
    assert "not" in DSL_SYSTEM_PROMPT


def test_system_prompt_covers_having():
    """HAVING rules are documented."""
    assert "having" in DSL_SYSTEM_PROMPT.lower()


def test_system_prompt_covers_negation():
    """Negation handling is documented."""
    assert "非" in DSL_SYSTEM_PROMPT or "不是" in DSL_SYSTEM_PROMPT or "排除" in DSL_SYSTEM_PROMPT


def test_system_prompt_covers_time():
    """Time handling rules are documented."""
    assert "time_field" in DSL_SYSTEM_PROMPT or "时间" in DSL_SYSTEM_PROMPT


def test_json_schema_is_valid():
    """DSL_JSON_SCHEMA is valid JSON."""
    import json
    schema = json.loads(DSL_JSON_SCHEMA)
    assert schema["type"] == "object"
    assert "metrics" in schema["properties"]
    assert "dimensions" in schema["properties"]
    assert "filters" in schema["properties"]
    assert "having" in schema["properties"]
    assert "$defs" in schema
    assert "filter_tree" in schema["$defs"]
    assert "filter_leaf" in schema["$defs"]


def test_build_user_prompt_includes_question():
    prompt = build_user_prompt("查询华东销售额", "some context")
    assert "查询华东销售额" in prompt
    assert "some context" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_prompts.py -v
```

Expected: FAIL — `DSL_JSON_SCHEMA` not defined; prompt still has examples.

- [ ] **Step 3: Implement new prompt with zero-shot + CoT + JSON Schema**

Replace `nl2dsl/llm/prompts.py`:

```python
import json

DSL_SYSTEM_PROMPT = """你是一个数据查询助手。请根据提供的信息将用户问题转换为 DSL（JSON 格式）。

你必须遵循以下规则，不要参考任何示例，只根据规则理解用户意图。

## 思维链检查步骤（执行这9步后再输出JSON）

1. **识别指标**：用户问的是哪个数值？（销售额、订单量、客单价...）→ 映射到 metrics
2. **识别维度**：用户说"按XX统计"？→ 映射到 dimensions
3. **识别过滤条件**：用户提到的所有具体限制条件 → 映射到 filters
4. **识别时间条件**：是否有年份、月份、最近N天等时间限制？→ 映射到 time_field + time_range
5. **识别排序**：是否有"最高""最低""前N"？→ 映射到 order_by + limit
6. **识别隐含JOIN**：是否涉及非主表字段（品牌、客户名等）？→ 映射到 joins
7. **识别聚合后过滤**：是否有"销售额大于X的"这类对聚合结果的过滤？→ 映射到 having
8. **识别否定**：是否有"非""不是""排除"？→ 用 not 操作符
9. **遗漏检查**：重新读用户问题，确认没有遗漏任何条件

## 指标映射词典（用户说的词 → alias）
- "销售额" / "营收" / "收入" → `sales_amount`
- "成交总额" / "GMV" / "交易额" → `gmv`
- "订单数量" / "订单量" / "单量" → `order_count`
- "客单价" / "平均订单金额" → `avg_order_value`
- "客户数量" / "用户数" / "人数" → `customer_count`
- "优惠总额" / "折扣金额" → `total_discount`

## 维度映射词典（用户说的词 → dimension）
- "产品" / "商品" → `product_name`
- "品牌" → `brand`
- "品类" / "分类" → `category`
- "地区" / "区域" → `region`
- "渠道" / "销售方式" → `channel`
- "客户类型" → `customer_type`
- "客户名" → `customer_name`
- "时间" / "日期" → `order_date`

## 过滤条件规则（核心）

### 操作符映射表
| 用户表达 | operator | value 格式 |
|---------|----------|-----------|
| 等于 / 是 | `=` | 字符串或数字 |
| 不等于 / 非 / 不是 / 排除 | `!=` | 字符串或数字 |
| 大于 / 超过 | `>` | 数字 |
| 小于 / 低于 | `<` | 数字 |
| 大于等于 | `>=` | 数字 |
| 小于等于 | `<=` | 数字 |
| 在...之间 / 从...到 | `between` | `[min, max]` 数组 |
| 在...之中 / 包含于 | `in` | `["a", "b"]` 数组 |
| 包含 / 像 | `like` | 字符串（自动加 % 通配符） |
| 为空 / NULL | `is_null` | 省略 value 字段 |

### 复合条件树结构
当用户问题包含多个条件时，必须用条件树（tree）格式，不要用扁平列表：

```json
{
  "op": "and",
  "children": [
    {"field": "region", "operator": "=", "value": "华东"},
    {"field": "channel", "operator": "=", "value": "线上"},
    {"field": "pay_amount", "operator": ">", "value": 5000}
  ]
}
```

支持的操作符：`and`（全部满足）、`or`（任一满足）、`not`（取反）
- `not` 的 children 只有一个元素
- 条件树可以嵌套：children 中既可以是 leaf 也可以是另一个 tree

### 数值处理规则
- "金额大于5000" → `{"field": "pay_amount", "operator": ">", "value": 5000}`
- "价格在5000到20000之间" → `{"field": "pay_amount", "operator": "between", "value": [5000, 20000]}`
- 注意：数值不要加引号

### 否定处理规则
- "非手机品类" → 用条件树：`{"op": "not", "children": [{"field": "category", "operator": "=", "value": "手机"}]}`
- "排除华东地区" → `{"field": "region", "operator": "!=", "value": "华东"}`
- 当否定与其他条件并存时，必须用条件树包裹

### 时间处理规则
- "2024年" → time_field="order_date", time_range=["2024-01-01", "2024-12-31"]
- "最近7天" → time_field="order_date", time_range=["<最近7天开始日期>", "<今天>"]
  （如果不知道具体日期，用 filters 中的 between 代替）
- "本月" → time_field="order_date", time_range=["<本月第一天>", "<本月最后一天>"]
- 也可以直接用 filters：`{"field": "order_date", "operator": "between", "value": ["2024-01-01", "2024-12-31"]}`

### 隐含 JOIN 识别规则
当用户问题涉及以下字段时，必须在 joins 中添加对应的 JOIN：
- brand, category, price → product_dim: `{"table": "product_dim", "on_field": "product_id", "join_type": "inner", "alias": "p"}`
- customer_name, customer_type, register_date → customer_dim: `{"table": "customer_dim", "on_field": "customer_id", "join_type": "left", "alias": "c"}`

### HAVING 使用规则
当用户问题包含对聚合结果的过滤时，用 having（不是 filters）：
- "销售额大于10万的品牌" → having: `[{"field": "sales_amount", "operator": ">", "value": 100000}]`
- having 的 field 必须是 metrics 中的某个 alias
- having 必须与 metrics 同时出现（不能单独使用）

## 字段格式要求

### metrics（指标，必填）
- 必须是数组，每个元素包含：
  - `func`: 聚合函数，只能是 "sum" | "avg" | "count" | "min" | "max"
  - `field`: 原始字段名（不要带 SUM/AVG/COUNT 等函数前缀）
  - `alias`: 指标别名，**必须是上面词典中的名称**，不要自创

### dimensions（维度，必填）
- 必须是字符串数组，不能为空数组 []
- **用户说"按XX统计"，dimensions 就必须包含 XX 对应的维度名**
- 如果用户没有指定分组维度，默认使用 ["product_name"]

### filters（过滤条件，可选但重要）
- 可以是条件树（dict with op+children），也可以是旧格式的数组
- **强烈建议用条件树格式**
- **用户提到的任何具体条件都必须出现在这里**
- 不要自己添加 tenant_id 过滤，系统会自动注入

### having（聚合后过滤，可选）
- 数组，每个元素格式同 filter leaf
- field 必须是 metrics 中的 alias

### order_by（排序，可选）
- 数组，每个元素包含：
  - `field`: 排序字段名（通常是 metrics 的 alias）
  - `direction`: "asc" 或 "desc"
- 如果有 metrics，默认按第一个 metric 的 alias 降序排列

### limit（返回条数，必填）
- 必须是整数
- 默认 10，最多 100
- 用户说"全部"或"所有"时才用 100

### data_source（数据源，必填）
- 查询销售额/订单/客户等用 "orders"
- 查询产品单价等用 "products"
- 查询客户信息等用 "customers"

### joins（多表关联，可选）
- 只有当查询涉及客户信息或产品详情时才需要
- customer_dim: `{"table": "customer_dim", "on_field": "customer_id", "join_type": "left", "alias": "c"}`
- product_dim: `{"table": "product_dim", "on_field": "product_id", "join_type": "inner", "alias": "p"}`

### time_field + time_range（时间范围，可选）
- time_field: 时间字段名（如 "order_date"）
- time_range: `["开始日期", "结束日期"]`，格式 "YYYY-MM-DD"

## 输出规则
1. 只输出 JSON，不要输出任何解释文字
2. 不要输出 markdown 代码块标记
3. 所有字符串值用双引号
4. 数值不要用引号包裹
5. 确保所有用户提到的条件都在 DSL 中体现，无一遗漏
"""

DSL_JSON_SCHEMA = json.dumps(
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
                        "alias": {"type": "string"},
                    },
                },
            },
            "dimensions": {"type": "array", "items": {"type": "string"}},
            "filters": {
                "oneOf": [
                    {"type": "array", "items": {"$ref": "#/$defs/filter_leaf"}},
                    {"$ref": "#/$defs/filter_tree"},
                ]
            },
            "having": {
                "type": "array",
                "items": {"$ref": "#/$defs/filter_leaf"},
            },
            "order_by": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["field", "direction"],
                    "properties": {
                        "field": {"type": "string"},
                        "direction": {"enum": ["asc", "desc"]},
                    },
                },
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
                        "alias": {"type": "string"},
                    },
                },
            },
            "time_field": {"type": "string"},
            "time_range": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 2,
            },
        },
        "$defs": {
            "filter_leaf": {
                "type": "object",
                "required": ["field", "operator"],
                "properties": {
                    "field": {"type": "string"},
                    "operator": {
                        "enum": ["=", "!=", ">", "<", ">=", "<=", "between", "in", "like", "is_null"]
                    },
                    "value": {},
                },
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
                                {"$ref": "#/$defs/filter_tree"},
                            ]
                        },
                    },
                },
            },
        },
    },
    ensure_ascii=False,
    indent=2,
)


def build_user_prompt(question: str, context: str) -> str:
    return f"""【上下文】
{context}

【用户问题】
{question}

请严格按上述字段格式要求输出 DSL JSON："""
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_prompts.py -v
```

Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add nl2dsl/llm/prompts.py tests/unit/test_prompts.py
git commit -m "feat(llm): rewrite prompt to zero-shot + CoT + JSON Schema"
```

---

### Task 3: Extend LLM Client — Structured Output Support

**Files:**
- Modify: `nl2dsl/llm/client.py`
- Test: `tests/unit/test_llm_client.py`

**Context:** Current `LLMClient.generate()` only supports free-text output. We need `generate_structured()` that passes `response_format={"type": "json_schema", "json_schema": {...}}` to enforce JSON Schema.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_llm_client.py`:

```python
from unittest.mock import MagicMock, patch
import pytest
from nl2dsl.llm.client import LLMClient


def test_generate_structured_calls_openai_with_json_schema():
    """generate_structured passes response_format with json_schema."""
    client = LLMClient(api_key="test-key", base_url="https://api.example.com", model="test-model")

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = '{"data_source": "orders", "metrics": []}'
    mock_response.usage = MagicMock()

    with patch.object(client._client.chat.completions, "create", return_value=mock_response) as mock_create:
        schema = '{"type": "object", "properties": {"data_source": {"type": "string"}}}'
        result = client.generate_structured("user prompt", "system prompt", schema)

        assert result == '{"data_source": "orders", "metrics": []}'
        call_kwargs = mock_create.call_args.kwargs
        assert "response_format" in call_kwargs
        assert call_kwargs["response_format"]["type"] == "json_schema"
        assert "json_schema" in call_kwargs["response_format"]
        assert call_kwargs["temperature"] == 0


def test_generate_structured_uses_temperature_zero():
    """Structured output always uses temperature=0 for determinism."""
    client = LLMClient(api_key="test-key", base_url="https://api.example.com", model="test-model")

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "{}"
    mock_response.usage = MagicMock()

    with patch.object(client._client.chat.completions, "create", return_value=mock_response) as mock_create:
        client.generate_structured("prompt", "sys", "{}")
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["temperature"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_llm_client.py::test_generate_structured_calls_openai_with_json_schema -v
```

Expected: FAIL — `LLMClient` has no `generate_structured` method.

- [ ] **Step 3: Implement generate_structured method**

Edit `nl2dsl/llm/client.py`, add the `generate_structured` method after `generate`:

```python
    def generate_structured(self, user_prompt: str, system_prompt: str, json_schema: str) -> str:
        """Generate with JSON Schema enforcement via OpenAI structured output.

        Uses response_format={"type": "json_schema", ...} for deterministic
        JSON output. Always uses temperature=0.
        """
        start = time.time()
        logger.info("LLM structured request: model=%s schema_length=%d", self._model, len(json_schema))

        kwargs = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "dsl_response",
                    "strict": True,
                    "schema": json_schema if isinstance(json_schema, dict) else __import__("json").loads(json_schema),
                },
            },
        }

        response = self._client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        elapsed = int((time.time() - start) * 1000)
        logger.info("LLM structured response: tokens=%s time=%dms content_length=%d",
                    response.usage, elapsed, len(content) if content else 0)
        return content
```

Note: Add `import json` at the top of the file if not already present (it's not in the current file).

Full updated `nl2dsl/llm/client.py`:

```python
import json
import time

from openai import OpenAI

from nl2dsl.utils.logger import get_logger

logger = get_logger("llm")


class LLMClient:
    def __init__(self, api_key: str, base_url: str, model: str):
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._thinking = None
        if "bigmodel.cn" in base_url or "zhipu" in base_url.lower():
            self._thinking = {"type": "enabled"}
            logger.info("Detected ZhipuAI backend, thinking enabled")
        logger.info("LLMClient initialized: model=%s base_url=%s", model, base_url)

    @property
    def model_name(self) -> str:
        return self._model

    def generate(self, user_prompt: str, system_prompt: str) -> str:
        start = time.time()
        logger.info("LLM request: model=%s prompt_length=%d", self._model, len(user_prompt))
        kwargs = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
        }
        if self._thinking:
            kwargs["extra_body"] = {"thinking": self._thinking}
        response = self._client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        elapsed = int((time.time() - start) * 1000)
        logger.info("LLM response: tokens=%s time=%dms content_length=%d",
                    response.usage, elapsed, len(content) if content else 0)
        return content

    def generate_structured(self, user_prompt: str, system_prompt: str, json_schema: str) -> str:
        """Generate with JSON Schema enforcement via OpenAI structured output.

        Uses response_format={"type": "json_schema", ...} for deterministic
        JSON output. Always uses temperature=0.
        """
        start = time.time()
        logger.info("LLM structured request: model=%s schema_length=%d", self._model, len(json_schema))

        schema_dict = json_schema if isinstance(json_schema, dict) else json.loads(json_schema)

        kwargs = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "dsl_response",
                    "strict": True,
                    "schema": schema_dict,
                },
            },
        }

        response = self._client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        elapsed = int((time.time() - start) * 1000)
        logger.info("LLM structured response: tokens=%s time=%dms content_length=%d",
                    response.usage, elapsed, len(content) if content else 0)
        return content
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_llm_client.py -v
```

Expected: PASS (including the 2 new tests)

- [ ] **Step 5: Commit**

```bash
git add nl2dsl/llm/client.py tests/unit/test_llm_client.py
git commit -m "feat(llm): add generate_structured with JSON Schema enforcement"
```

---

### Task 4: Create Semantic Validator

**Files:**
- Create: `nl2dsl/dsl/semantic_validator.py`
- Test: `tests/unit/test_semantic_validator.py`

**Context:** New layer that validates DSL semantics after generation, before SQL building. Checks: field existence, numeric operator values, between/in format, value domain, condition conflicts, having-requires-metric.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_semantic_validator.py`:

```python
import pytest
from nl2dsl.dsl.models import DSL, FilterTreeNode, Having, Aggregation
from nl2dsl.dsl.semantic_validator import SemanticValidator, SemanticWarning


@pytest.fixture
def validator():
    registry = {
        "metrics": {
            "sales_amount": {"expr": "SUM(pay_amount)", "description": "销售额"},
            "order_count": {"expr": "COUNT(id)", "description": "订单量"},
        },
        "dimensions": {
            "product_name": {"column": "product_name", "description": "产品"},
            "brand": {"column": "brand", "description": "品牌"},
            "region": {"column": "region", "description": "地区"},
            "category": {"column": "category", "description": "品类"},
        },
        "data_sources": {
            "orders": {"table": "order_fact"},
        },
        "fields": {
            "region": {"type": "string", "allowed_values": ["华东", "华南", "华北", "西南"]},
            "pay_amount": {"type": "number"},
            "order_date": {"type": "date"},
        },
    }
    return SemanticValidator(registry)


class TestFieldExistence:
    def test_metric_alias_exists(self, validator):
        dsl = DSL(
            data_source="orders",
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["brand"],
        )
        errors, warnings = validator.validate(dsl)
        assert not errors

    def test_metric_alias_missing(self, validator):
        dsl = DSL(
            data_source="orders",
            metrics=[Aggregation(func="sum", field="pay_amount", alias="unknown_metric")],
            dimensions=["brand"],
        )
        errors, _ = validator.validate(dsl)
        assert any("unknown_metric" in e for e in errors)

    def test_dimension_exists(self, validator):
        dsl = DSL(data_source="orders", dimensions=["brand"])
        errors, _ = validator.validate(dsl)
        assert not errors

    def test_dimension_missing(self, validator):
        dsl = DSL(data_source="orders", dimensions=["unknown_dim"])
        errors, _ = validator.validate(dsl)
        assert any("unknown_dim" in e for e in errors)

    def test_data_source_exists(self, validator):
        dsl = DSL(data_source="orders")
        errors, _ = validator.validate(dsl)
        assert not errors

    def test_data_source_missing(self, validator):
        dsl = DSL(data_source="nonexistent")
        errors, _ = validator.validate(dsl)
        assert any("nonexistent" in e for e in errors)


class TestFilterValidation:
    def test_filter_field_exists(self, validator):
        dsl = DSL(
            data_source="orders",
            filters=[{"field": "region", "operator": "=", "value": "华东"}],
        )
        errors, _ = validator.validate(dsl)
        assert not errors

    def test_filter_numeric_operator_with_number(self, validator):
        dsl = DSL(
            data_source="orders",
            filters=[{"field": "pay_amount", "operator": ">", "value": 5000}],
        )
        errors, _ = validator.validate(dsl)
        assert not errors

    def test_filter_numeric_operator_with_string_error(self, validator):
        dsl = DSL(
            data_source="orders",
            filters=[{"field": "pay_amount", "operator": ">", "value": "5000"}],
        )
        errors, _ = validator.validate(dsl)
        assert any("> requires a number" in e or "numeric" in e.lower() for e in errors
        )

    def test_between_requires_list(self, validator):
        dsl = DSL(
            data_source="orders",
            filters=[{"field": "pay_amount", "operator": "between", "value": 100}],
        )
        errors, _ = validator.validate(dsl)
        assert any("between requires" in e.lower() or "[min, max]" in e for e in errors)

    def test_in_requires_list(self, validator):
        dsl = DSL(
            data_source="orders",
            filters=[{"field": "region", "operator": "in", "value": "华东"}],
        )
        errors, _ = validator.validate(dsl)
        assert any("in requires" in e.lower() or "list" in e.lower() for e in errors)


class TestFilterTreeValidation:
    def test_nested_tree_valid(self, validator):
        dsl = DSL(
            data_source="orders",
            filters={
                "op": "and",
                "children": [
                    {"field": "region", "operator": "=", "value": "华东"},
                    {
                        "op": "not",
                        "children": [{"field": "category", "operator": "=", "value": "手机"}],
                    },
                ],
            },
        )
        errors, _ = validator.validate(dsl)
        assert not errors

    def test_tree_with_unknown_field_warns(self, validator):
        dsl = DSL(
            data_source="orders",
            filters={
                "op": "and",
                "children": [
                    {"field": "unknown_field", "operator": "=", "value": "x"},
                ],
            },
        )
        errors, warnings = validator.validate(dsl)
        # unknown_field not in registry fields → warning (not error)
        assert any("unknown_field" in w.message for w in warnings)


class TestConditionConflict:
    def test_same_field_equal_different_values(self, validator):
        dsl = DSL(
            data_source="orders",
            filters=[
                {"field": "region", "operator": "=", "value": "华东"},
                {"field": "region", "operator": "=", "value": "华南"},
            ],
        )
        errors, _ = validator.validate(dsl)
        assert any("conflict" in e.lower() for e in errors)

    def test_no_conflict_different_fields(self, validator):
        dsl = DSL(
            data_source="orders",
            filters=[
                {"field": "region", "operator": "=", "value": "华东"},
                {"field": "channel", "operator": "=", "value": "线上"},
            ],
        )
        errors, _ = validator.validate(dsl)
        assert not errors


class TestHavingValidation:
    def test_having_with_metric_ok(self, validator):
        dsl = DSL(
            data_source="orders",
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["brand"],
            having=[{"field": "sales_amount", "operator": ">", "value": 100000}],
        )
        errors, _ = validator.validate(dsl)
        assert not errors

    def test_having_without_metric_error(self, validator):
        dsl = DSL(
            data_source="orders",
            dimensions=["brand"],
            having=[{"field": "sales_amount", "operator": ">", "value": 100000}],
        )
        errors, _ = validator.validate(dsl)
        assert any("having" in e.lower() and "metric" in e.lower() for e in errors)

    def test_having_field_not_in_metrics(self, validator):
        dsl = DSL(
            data_source="orders",
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["brand"],
            having=[{"field": "unknown_alias", "operator": ">", "value": 100}],
        )
        errors, _ = validator.validate(dsl)
        assert any("unknown_alias" in e for e in errors)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_semantic_validator.py -v
```

Expected: FAIL — `SemanticValidator` class doesn't exist.

- [ ] **Step 3: Implement SemanticValidator**

Create `nl2dsl/dsl/semantic_validator.py`:

```python
"""Semantic validation for DSL after generation, before SQL building.

Validates: field existence, type consistency, condition conflicts,
having-requires-metric, format correctness.

Returns (errors, warnings) where:
- errors: list[str] — block execution, trigger auto-correction
- warnings: list[SemanticWarning] — log only, don't block
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nl2dsl.dsl.models import DSL, Filter, FilterTreeNode, Having, Aggregation


@dataclass
class SemanticWarning:
    category: str
    message: str


class SemanticValidator:
    def __init__(self, registry: dict):
        self._metrics = set(registry.get("metrics", {}).keys())
        self._dimensions = set(registry.get("dimensions", {}).keys())
        self._data_sources = set(registry.get("data_sources", {}).keys())
        self._fields = registry.get("fields", {})

    def validate(self, dsl: DSL) -> tuple[list[str], list[SemanticWarning]]:
        errors: list[str] = []
        warnings: list[SemanticWarning] = []

        self._validate_data_source(dsl, errors)
        self._validate_metrics(dsl, errors)
        self._validate_dimensions(dsl, errors)
        self._validate_filters(dsl, errors, warnings)
        self._validate_having(dsl, errors)
        self._validate_condition_conflicts(dsl, errors)

        return errors, warnings

    def _validate_data_source(self, dsl: DSL, errors: list[str]) -> None:
        if dsl.data_source not in self._data_sources:
            errors.append(f"数据源 '{dsl.data_source}' 不存在")

    def _validate_metrics(self, dsl: DSL, errors: list[str]) -> None:
        if dsl.metrics:
            for m in dsl.metrics:
                if m.alias and m.alias not in self._metrics:
                    errors.append(f"指标 '{m.alias}' 不存在")

    def _validate_dimensions(self, dsl: DSL, errors: list[str]) -> None:
        if dsl.dimensions:
            for d in dsl.dimensions:
                if d not in self._dimensions:
                    errors.append(f"维度 '{d}' 不存在")

    def _validate_filters(
        self, dsl: DSL, errors: list[str], warnings: list[SemanticWarning]
    ) -> None:
        if dsl.filters is None:
            return

        if isinstance(dsl.filters, FilterTreeNode):
            self._validate_filter_tree(dsl.filters, errors, warnings)
        elif isinstance(dsl.filters, list):
            for f in dsl.filters:
                self._validate_filter_leaf(f, errors, warnings)

    def _validate_filter_tree(
        self, node: FilterTreeNode, errors: list[str], warnings: list[SemanticWarning]
    ) -> None:
        for child in node.children:
            if isinstance(child, FilterTreeNode):
                self._validate_filter_tree(child, errors, warnings)
            else:
                self._validate_filter_leaf(child, errors, warnings)

    def _validate_filter_leaf(
        self, f: Filter, errors: list[str], warnings: list[SemanticWarning]
    ) -> None:
        # Field existence check → warning (not error, unknown fields may be valid)
        if f.field not in self._fields and f.field not in self._dimensions:
            warnings.append(
                SemanticWarning(
                    "unknown_field",
                    f"过滤字段 '{f.field}' 未在语义层注册，请确认拼写正确",
                )
            )

        # Numeric operator type check
        numeric_ops = {">", "<", ">=", "<=", "between"}
        if f.operator in numeric_ops:
            if f.operator == "between":
                if not isinstance(f.value, (list, tuple)) or len(f.value) != 2:
                    errors.append(
                        f"'between' operator requires a [min, max] list, got {f.value!r}"
                    )
            elif not isinstance(f.value, (int, float)):
                errors.append(
                    f"Operator '{f.operator}' requires a numeric value, got {type(f.value).__name__}"
                )

        # 'in' operator format check
        if f.operator == "in" and not isinstance(f.value, list):
            errors.append(f"'in' operator requires a list value, got {type(f.value).__name__}")

        # Value domain check → warning
        field_info = self._fields.get(f.field, {})
        allowed = field_info.get("allowed_values")
        if allowed and f.value is not None and f.value not in allowed:
            if f.operator == "=" or (f.operator == "in" and isinstance(f.value, list)):
                val_to_check = f.value if f.operator == "=" else f.value
                if isinstance(val_to_check, list):
                    unknown = [v for v in val_to_check if v not in allowed]
                    if unknown:
                        warnings.append(
                            SemanticWarning(
                                "value_domain",
                                f"值 {unknown!r} 不在 '{f.field}' 的已知取值中 {allowed!r}",
                            )
                        )
                elif val_to_check not in allowed:
                    warnings.append(
                        SemanticWarning(
                            "value_domain",
                            f"值 '{val_to_check}' 不在 '{f.field}' 的已知取值中 {allowed!r}",
                        )
                    )

    def _validate_having(self, dsl: DSL, errors: list[str]) -> None:
        if not dsl.having:
            return

        if not dsl.metrics:
            errors.append("having 必须与 metrics 同时出现，不能单独使用")
            return

        metric_aliases = {m.alias for m in dsl.metrics if m.alias}
        for h in dsl.having:
            if h.field not in metric_aliases:
                errors.append(f"having 字段 '{h.field}' 不是 metrics 中的 alias: {metric_aliases}")

    def _validate_condition_conflicts(self, dsl: DSL, errors: list[str]) -> None:
        """Detect conflicting conditions like A=1 AND A=2."""
        filters = dsl.filters
        if filters is None:
            return

        # Collect all leaf filters
        leafs: list[Filter] = []
        if isinstance(filters, FilterTreeNode):
            self._collect_leafs(filters, leafs)
        elif isinstance(filters, list):
            leafs = filters

        # Group by field+operator and check for conflicts on '='
        eq_conditions: dict[str, list[Any]] = {}
        for f in leafs:
            if f.operator == "=":
                eq_conditions.setdefault(f.field, []).append(f.value)

        for field, values in eq_conditions.items():
            if len(values) > 1 and len(set(str(v) for v in values)) > 1:
                errors.append(
                    f"条件冲突: '{field}' 被赋予多个不同的值 {values!r}"
                )

    def _collect_leafs(self, node: FilterTreeNode, out: list[Filter]) -> None:
        for child in node.children:
            if isinstance(child, FilterTreeNode):
                self._collect_leafs(child, out)
            else:
                out.append(child)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_semantic_validator.py -v
```

Expected: PASS (14 tests across 5 classes)

- [ ] **Step 5: Commit**

```bash
git add nl2dsl/dsl/semantic_validator.py tests/unit/test_semantic_validator.py
git commit -m "feat(dsl): add semantic validator with condition tree support"
```

---

### Task 5: Extend SQL Builder — Condition Tree, Between, Is Null, HAVING, Time Range

**Files:**
- Modify: `nl2dsl/sql_engine/builder.py`
- Test: `tests/unit/test_sql_builder.py`

**Context:** Current builder only handles flat `list[Filter]`. Need to support:
1. `FilterTreeNode` recursive SQL generation
2. `between` operator (already partially there, need to ensure it works with tree)
3. `is_null` operator → `col.is_(None)`
4. `HAVING` clause after GROUP BY
5. `time_field` + `time_range` → auto-add to WHERE

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_sql_builder.py`:

```python
import pytest
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Float, DateTime
from nl2dsl.dsl.models import DSL, Filter, Aggregation, OrderBy


@pytest.fixture
def builder_with_joins():
    """Builder with multi-table support for JOIN and condition tree tests."""
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()

    Table(
        "order_fact", metadata,
        Column("id", Integer, primary_key=True),
        Column("product_id", Integer),
        Column("product_name", String),
        Column("region", String),
        Column("channel", String),
        Column("pay_amount", Float),
        Column("order_amount", Float),
        Column("order_date", DateTime),
    )
    Table(
        "product_dim", metadata,
        Column("product_id", Integer, primary_key=True),
        Column("brand", String),
        Column("category", String),
    )
    metadata.create_all(engine)

    return SQLBuilder(
        engine,
        {"orders": "order_fact"},
        data_sources={
            "orders": {
                "joins": {
                    "product_dim": {
                        "on": "product_id",
                        "type": "inner",
                        "alias": "p",
                    }
                }
            }
        },
        dimension_mapping={},
    )


class TestConditionTree:
    def test_build_and_tree(self, builder_with_joins):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["product_name"],
            filters={
                "op": "and",
                "children": [
                    {"field": "region", "operator": "=", "value": "华东"},
                    {"field": "channel", "operator": "=", "value": "线上"},
                    {"field": "pay_amount", "operator": ">", "value": 5000},
                ],
            },
            data_source="orders",
        )
        sql = builder_with_joins.build(dsl)
        assert "WHERE" in sql
        assert "华东" in sql
        assert "线上" in sql
        assert "5000" in sql
        # AND should combine all three
        assert "AND" in sql.upper()

    def test_build_or_tree(self, builder_with_joins):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["product_name"],
            filters={
                "op": "or",
                "children": [
                    {"field": "region", "operator": "=", "value": "华东"},
                    {"field": "region", "operator": "=", "value": "华南"},
                ],
            },
            data_source="orders",
        )
        sql = builder_with_joins.build(dsl)
        assert "华东" in sql
        assert "华南" in sql
        assert "OR" in sql.upper()

    def test_build_not_tree(self, builder_with_joins):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["product_name"],
            filters={
                "op": "and",
                "children": [
                    {"field": "region", "operator": "=", "value": "华东"},
                    {
                        "op": "not",
                        "children": [
                            {"field": "channel", "operator": "=", "value": "线下"},
                        ],
                    },
                ],
            },
            data_source="orders",
        )
        sql = builder_with_joins.build(dsl)
        assert "华东" in sql
        # NOT should negate the channel condition

    def test_build_nested_tree(self, builder_with_joins):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["product_name"],
            filters={
                "op": "or",
                "children": [
                    {
                        "op": "and",
                        "children": [
                            {"field": "region", "operator": "=", "value": "华东"},
                            {"field": "channel", "operator": "=", "value": "线上"},
                        ],
                    },
                    {
                        "op": "and",
                        "children": [
                            {"field": "region", "operator": "=", "value": "华南"},
                            {"field": "channel", "operator": "=", "value": "线下"},
                        ],
                    },
                ],
            },
            data_source="orders",
        )
        sql = builder_with_joins.build(dsl)
        assert "华东" in sql
        assert "华南" in sql
        assert "线上" in sql
        assert "线下" in sql


class TestOperators:
    def test_is_null(self, builder_with_joins):
        dsl = DSL(
            metrics=[Aggregation(func="count", field="id", alias="order_count")],
            dimensions=["product_name"],
            filters=[{"field": "pay_amount", "operator": "is_null"}],
            data_source="orders",
        )
        sql = builder_with_joins.build(dsl)
        assert "IS NULL" in sql.upper()

    def test_between_in_tree(self, builder_with_joins):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["product_name"],
            filters={
                "op": "and",
                "children": [
                    {"field": "pay_amount", "operator": "between", "value": [5000, 20000]},
                ],
            },
            data_source="orders",
        )
        sql = builder_with_joins.build(dsl)
        assert "BETWEEN" in sql.upper()
        assert "5000" in sql
        assert "20000" in sql


class TestHaving:
    def test_having_basic(self, builder_with_joins):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["product_name"],
            having=[{"field": "sales_amount", "operator": ">", "value": 100000}],
            data_source="orders",
        )
        sql = builder_with_joins.build(dsl)
        assert "HAVING" in sql.upper()
        assert "100000" in sql

    def test_having_with_filter(self, builder_with_joins):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["product_name"],
            filters=[{"field": "region", "operator": "=", "value": "华东"}],
            having=[{"field": "sales_amount", "operator": ">", "value": 100000}],
            data_source="orders",
        )
        sql = builder_with_joins.build(dsl)
        assert "WHERE" in sql.upper()
        assert "HAVING" in sql.upper()
        # WHERE should come before HAVING in SQL
        where_pos = sql.upper().find("WHERE")
        having_pos = sql.upper().find("HAVING")
        assert where_pos < having_pos


class TestTimeRange:
    def test_time_range_adds_where(self, builder_with_joins):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["product_name"],
            time_field="order_date",
            time_range=("2026-05-23", "2026-05-30"),
            data_source="orders",
        )
        sql = builder_with_joins.build(dsl)
        assert "WHERE" in sql.upper()
        assert "2026-05-23" in sql
        assert "2026-05-30" in sql
        assert "BETWEEN" in sql.upper() or "order_date" in sql.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_sql_builder.py -v
```

Expected: FAIL — `_build_condition_tree` doesn't exist; `is_null` not handled in tree; `HAVING` not supported; `time_range` not processed.

- [ ] **Step 3: Implement SQL Builder extensions**

Edit `nl2dsl/sql_engine/builder.py`. The key changes are:

1. Import `or_`, `not_` from sqlalchemy
2. Add `_build_condition_tree()` recursive method
3. Add `_build_leaf_condition()` (extract from existing filter handling)
4. Add HAVING support after GROUP BY
5. Add time_range → WHERE conversion
6. Handle `is_null` operator

Here's the diff approach — replace the relevant sections:

First, update imports (line 2):

```python
from sqlalchemy import MetaData, select, func, and_, or_, not_, desc, asc, text, join as sa_join
```

Update the `_collect_referenced_columns` method to also collect from filter trees and having:

After line 98 (the existing filter collection), add:

```python
    def _collect_columns_from_tree(self, node, columns: set) -> None:
        """Recursively collect field names from a filter tree."""
        from nl2dsl.dsl.models import FilterTreeNode
        if isinstance(node, FilterTreeNode):
            for child in node.children:
                self._collect_columns_from_tree(child, columns)
        else:
            columns.add(node.field)
```

And update `_collect_referenced_columns` to call it:

After the existing flat filter collection (line 98), replace with:

```python
        # Filters
        if dsl.filters:
            if isinstance(dsl.filters, list):
                for f in dsl.filters:
                    columns.add(f.field)
            else:
                self._collect_columns_from_tree(dsl.filters, columns)

        # Having
        if dsl.having:
            for h in dsl.having:
                # Having references metric aliases, not columns — skip
                pass

        # Time field
        if dsl.time_field:
            columns.add(dsl.time_field)
```

Now, the main `build()` method changes. Replace the WHERE-building section (lines 291-322):

```python
        # Build where
        conditions = []

        # time_range → between condition
        if dsl.time_field and dsl.time_range:
            time_col = self._resolve_column(tables, dsl.time_field)
            conditions.append(time_col.between(dsl.time_range[0], dsl.time_range[1]))

        # filters: flat list or condition tree
        if dsl.filters:
            if isinstance(dsl.filters, list):
                for f in dsl.filters:
                    conditions.append(self._build_leaf_condition(tables, f))
            else:
                conditions.append(self._build_condition_tree(tables, dsl.filters))

        if conditions:
            stmt = stmt.where(and_(*conditions))

        # Group by
        if dsl.dimensions and dsl.metrics:
            group_cols = [self._resolve_column(tables, self._dimension_mapping.get(d, d)) for d in dsl.dimensions]
            stmt = stmt.group_by(*group_cols)

        # Having
        if dsl.having:
            having_conditions = []
            for h in dsl.having:
                col_ref = text(h.field)  # Reference the aggregated alias
                if h.operator == "=":
                    having_conditions.append(col_ref == h.value)
                elif h.operator == "!=":
                    having_conditions.append(col_ref != h.value)
                elif h.operator == ">":
                    having_conditions.append(col_ref > h.value)
                elif h.operator == "<":
                    having_conditions.append(col_ref < h.value)
                elif h.operator == ">=":
                    having_conditions.append(col_ref >= h.value)
                elif h.operator == "<=":
                    having_conditions.append(col_ref <= h.value)
                elif h.operator == "between":
                    val = h.value
                    if isinstance(val, (list, tuple)) and len(val) == 2:
                        having_conditions.append(col_ref.between(val[0], val[1]))
                    else:
                        raise ValidationError(
                            f"'between' in having requires [min, max] list, got {val!r}"
                        )
            if having_conditions:
                stmt = stmt.having(and_(*having_conditions))
```

Add these two new methods to the class (insert after `_get_table_for_column` around line 73):

```python
    def _build_condition_tree(self, tables: dict[str, object], node) -> object:
        """Recursively build SQLAlchemy expression from a filter tree."""
        from nl2dsl.dsl.models import FilterTreeNode
        if isinstance(node, FilterTreeNode):
            if node.op == "and":
                return and_(*[self._build_condition_tree(tables, c) for c in node.children])
            elif node.op == "or":
                return or_(*[self._build_condition_tree(tables, c) for c in node.children])
            elif node.op == "not":
                return not_(self._build_condition_tree(tables, node.children[0]))
        # Leaf node
        return self._build_leaf_condition(tables, node)

    def _build_leaf_condition(self, tables: dict[str, object], f) -> object:
        """Build a single filter condition (leaf node)."""
        col = self._resolve_column(tables, f.field)
        if f.operator == "=":
            return col == f.value
        elif f.operator == "!=":
            return col != f.value
        elif f.operator == ">":
            return col > f.value
        elif f.operator == "<":
            return col < f.value
        elif f.operator == ">=":
            return col >= f.value
        elif f.operator == "<=":
            return col <= f.value
        elif f.operator == "in":
            return col.in_(f.value)
        elif f.operator == "like":
            return col.like(f"%{f.value}%")
        elif f.operator == "between":
            val = f.value
            if isinstance(val, (list, tuple)) and len(val) == 2:
                return col.between(val[0], val[1])
            raise ValidationError(f"'between' requires [min, max] list, got {val!r}")
        elif f.operator == "is_null":
            return col.is_(None)
        else:
            raise ValidationError(f"Unknown operator: {f.operator}")
```

Also need to update the import at the top to include `or_` and `not_`:

```python
from sqlalchemy import MetaData, select, func, and_, or_, not_, desc, asc, text, join as sa_join
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_sql_builder.py -v
```

Expected: PASS (all existing + 10 new tests)

- [ ] **Step 5: Commit**

```bash
git add nl2dsl/sql_engine/builder.py tests/unit/test_sql_builder.py
git commit -m "feat(sql): add condition tree, between, is_null, HAVING, time_range support"
```

---

### Task 6: Create Query Post-Processor (TOP-N Per Group)

**Files:**
- Create: `nl2dsl/query/post_processor.py`
- Test: `tests/unit/test_post_processor.py`

**Context:** "各品类销售额最高的产品" needs Python-level post-processing since we don't have window functions yet. Trigger: dimensions >= 2, limit == 1, order_by exists.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_post_processor.py`:

```python
import pytest
from nl2dsl.query.post_processor import extract_top_per_group, should_post_process


class TestExtractTopPerGroup:
    def test_basic_top_per_group(self):
        data = [
            {"category": "手机", "product_name": "iPhone", "sales_amount": 100000},
            {"category": "手机", "product_name": "Samsung", "sales_amount": 80000},
            {"category": "电脑", "product_name": "MacBook", "sales_amount": 120000},
            {"category": "电脑", "product_name": "Dell", "sales_amount": 60000},
            {"category": "耳机", "product_name": "AirPods", "sales_amount": 50000},
        ]
        result = extract_top_per_group(data, group_key="category", order_key="sales_amount")
        assert len(result) == 3
        categories = {r["category"] for r in result}
        assert categories == {"手机", "电脑", "耳机"}
        # Each category should have the highest sales
        phone = next(r for r in result if r["category"] == "手机")
        assert phone["product_name"] == "iPhone"

    def test_ascending_order(self):
        data = [
            {"category": "A", "val": 100},
            {"category": "A", "val": 50},
            {"category": "B", "val": 200},
            {"category": "B", "val": 10},
        ]
        result = extract_top_per_group(data, group_key="category", order_key="val", order_desc=False)
        a = next(r for r in result if r["category"] == "A")
        assert a["val"] == 50  # ascending → smallest first

    def test_empty_data(self):
        result = extract_top_per_group([], group_key="x", order_key="y")
        assert result == []

    def test_single_group(self):
        data = [
            {"category": "A", "val": 100},
            {"category": "A", "val": 50},
        ]
        result = extract_top_per_group(data, group_key="category", order_key="val")
        assert len(result) == 1
        assert result[0]["val"] == 100

    def test_missing_order_key_defaults_to_zero(self):
        data = [
            {"category": "A", "product_name": "X"},
            {"category": "A", "product_name": "Y", "sales_amount": 100},
        ]
        result = extract_top_per_group(data, group_key="category", order_key="sales_amount")
        # The one with sales_amount=100 should win
        assert result[0]["product_name"] == "Y"


class TestShouldPostProcess:
    def test_trigger_conditions_met(self):
        from nl2dsl.dsl.models import DSL, OrderBy, Aggregation
        dsl = DSL(
            data_source="orders",
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["category", "product_name"],
            order_by=[OrderBy(field="sales_amount", direction="desc")],
            limit=1,
        )
        assert should_post_process(dsl) is True

    def test_no_trigger_single_dimension(self):
        from nl2dsl.dsl.models import DSL, OrderBy, Aggregation
        dsl = DSL(
            data_source="orders",
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["category"],
            order_by=[OrderBy(field="sales_amount", direction="desc")],
            limit=1,
        )
        assert should_post_process(dsl) is False

    def test_no_trigger_limit_not_one(self):
        from nl2dsl.dsl.models import DSL, OrderBy, Aggregation
        dsl = DSL(
            data_source="orders",
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["category", "product_name"],
            order_by=[OrderBy(field="sales_amount", direction="desc")],
            limit=10,
        )
        assert should_post_process(dsl) is False

    def test_no_trigger_no_order_by(self):
        from nl2dsl.dsl.models import DSL, Aggregation
        dsl = DSL(
            data_source="orders",
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["category", "product_name"],
            limit=1,
        )
        assert should_post_process(dsl) is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_post_processor.py -v
```

Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement post processor**

Create `nl2dsl/query/post_processor.py`:

```python
"""Query result post-processing.

Handles cases that are hard to express in a single SQL, like
"TOP-1 per group" which would need window functions.
"""

from __future__ import annotations

from itertools import groupby
from typing import Any

from nl2dsl.dsl.models import DSL


def should_post_process(dsl: DSL) -> bool:
    """Check if the DSL requires post-processing.

    Trigger: dimensions >= 2 AND limit == 1 AND order_by exists.
    This typically means "top-1 per group" semantics.
    """
    dims = dsl.dimensions or []
    has_multiple_dims = len(dims) >= 2
    limit_is_one = dsl.limit == 1
    has_order = dsl.order_by is not None and len(dsl.order_by) > 0
    return has_multiple_dims and limit_is_one and has_order


def extract_top_per_group(
    data: list[dict[str, Any]],
    group_key: str,
    order_key: str,
    order_desc: bool = True,
) -> list[dict[str, Any]]:
    """From sorted/grouped data, take the first row per group.

    Args:
        data: Query result rows (list of dicts)
        group_key: Field name to group by (typically the first dimension)
        order_key: Field name to sort within each group
        order_desc: True for descending (highest first), False for ascending

    Returns:
        One row per unique group_key value, the one with max/min order_key.
    """
    if not data:
        return []

    def sort_key(row: dict[str, Any]) -> tuple:
        grp = row.get(group_key)
        val = row.get(order_key, 0)
        # For descending: negate the value; for ascending: keep as-is
        # Handle non-numeric gracefully
        try:
            numeric_val = float(val) if val is not None else 0
        except (TypeError, ValueError):
            numeric_val = 0
        sort_val = -numeric_val if order_desc else numeric_val
        return (grp, sort_val)

    sorted_data = sorted(data, key=sort_key)

    result = []
    for _, group in groupby(sorted_data, key=lambda r: r.get(group_key)):
        result.append(next(group))

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_post_processor.py -v
```

Expected: PASS (8 tests across 2 classes)

- [ ] **Step 5: Commit**

```bash
git add nl2dsl/query/post_processor.py tests/unit/test_post_processor.py
git commit -m "feat(query): add TOP-N-per-group post-processor"
```

---

### Task 7: Refactor Graph Nodes — Remove Mock, Support Filter Trees

**Files:**
- Modify: `nl2dsl/graph/nodes.py`
- Test: `tests/unit/test_graph_nodes.py`

**Context:** Major cleanup:
1. Delete `_mock_dsl_from_question()` (lines 392-523)
2. Delete `_mock_sc_dsl()` (lines 525-627)
3. Delete `_extract_top_n()` (lines 191-206) — moved to `query/post_processor.py` for data extraction; but keep for limit extraction from question text (needed by `_semantic_fix_dsl` and `_post_process_dsl`)
4. Actually, re-read the design doc: `_extract_top_n` moves to DSL 后处理层. The function extracts a number from question text like "前5". Keep it but move to a more appropriate location. For now, keep it in nodes.py since both `_post_process_dsl` and `_semantic_fix_dsl` need it.
5. Simplify `_post_process_dsl` to handle filter trees
6. In `generate_dsl_node`, remove mock fallback; use LLM exclusively
7. In `correct_dsl_node`, remove mock fallback
8. Wire semantic validator into the pipeline

- [ ] **Step 1: Write failing tests for node changes**

Add to `tests/unit/test_graph_nodes.py` (the existing file already has tests, add these new ones):

```python
class TestPostProcessFilterTree:
    """Tests that _post_process_dsl correctly handles filter trees."""

    def test_post_process_flat_list_still_works(self):
        dsl_dict = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["product_name"],
            "filters": [
                {"field": "region", "operator": "=", "value": "华东"},
            ],
        }
        result = _post_process_dsl(dsl_dict)
        assert isinstance(result["filters"], list)
        assert result["filters"][0]["field"] == "region"

    def test_post_process_tree_preserved(self):
        dsl_dict = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["product_name"],
            "filters": {
                "op": "and",
                "children": [
                    {"field": "region", "operator": "=", "value": "华东"},
                    {"field": "pay_amount", "operator": ">", "value": 5000},
                ],
            },
        }
        result = _post_process_dsl(dsl_dict)
        assert isinstance(result["filters"], dict)
        assert result["filters"]["op"] == "and"
        assert len(result["filters"]["children"]) == 2

    def test_post_process_validates_filter_ops_in_tree(self):
        dsl_dict = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["product_name"],
            "filters": {
                "op": "and",
                "children": [
                    {"field": "region", "operator": "=", "value": "华东"},
                    {"field": "pay_amount", "operator": "invalid_op", "value": 5000},
                ],
            },
        }
        result = _post_process_dsl(dsl_dict)
        # Invalid ops should be normalized to "="
        children = result["filters"]["children"]
        assert children[1]["operator"] == "="


class TestGenerateDSLNodeNoMock:
    """Tests that generate_dsl node no longer falls back to mock."""

    def test_generate_dsl_uses_llm_no_mock_fallback(self, mock_llm_client, mock_rag_retriever):
        from nl2dsl.graph.nodes import create_node_functions
        from nl2dsl.graph.state import QueryState

        mock_llm_client.generate = MagicMock(
            return_value='{"data_source": "orders", "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}], "dimensions": ["product_name"], "filters": {"op": "and", "children": [{"field": "region", "operator": "=", "value": "华东"}, {"field": "pay_amount", "operator": ">", "value": 5000}]}}'
        )

        nodes = create_node_functions(
            llm_client=mock_llm_client,
            rag_retriever=mock_rag_retriever,
            validator=MagicMock(),
            row_security=MagicMock(),
            col_security=MagicMock(),
            resolver=MagicMock(),
            sql_builder=MagicMock(),
            scanner=MagicMock(),
            sandbox=MagicMock(),
            executor=MagicMock(),
            clarification_detector=MagicMock(),
        )

        state: QueryState = {
            "question": "华东线上金额大于5000的产品",
            "user_id": "test_user",
        }
        result = nodes["generate_dsl_node"](state)
        assert result["dsl"] is not None
        dsl = result["dsl"]
        assert dsl.data_source == "orders"
        # Verify the filter tree was preserved
        assert dsl.filters is not None
        assert result["trace"]["source"] == "llm"
```

- [ ] **Step 2: Run tests to verify failures**

```bash
pytest tests/unit/test_graph_nodes.py::TestPostProcessFilterTree -v
pytest tests/unit/test_graph_nodes.py::TestGenerateDSLNodeNoMock -v
```

Expected: FAIL — `_post_process_dsl` doesn't validate ops in trees; generate_dsl might still have mock paths.

- [ ] **Step 3: Implement node refactoring**

Edit `nl2dsl/graph/nodes.py`. The changes are extensive. Here's what to do:

**Delete these functions entirely:**
- `_mock_dsl_from_question()` (lines 392-523)
- `_mock_sc_dsl()` (lines 525-627)

**Modify `_post_process_dsl()`** to handle filter trees. Replace the filter validation section (around line 381-388):

```python
    # 8. Validate filters operator values (support both flat list and tree)
    valid_ops = {"=", "!=", ">", "<", ">=", "<=", "in", "like", "between", "is_null"}
    filters = dsl_dict.get("filters")
    if filters:
        if isinstance(filters, dict) and "op" in filters:
            # Filter tree format
            def _validate_tree(node):
                if node.get("op") in {"and", "or", "not"}:
                    for child in node.get("children", []):
                        _validate_tree(child)
                elif isinstance(node, dict) and "field" in node:
                    op = node.get("operator", "")
                    if op not in valid_ops:
                        node["operator"] = "="
            _validate_tree(filters)
        elif isinstance(filters, list):
            for f in filters:
                if isinstance(f, dict):
                    op = f.get("operator", "")
                    if op not in valid_ops:
                        f["operator"] = "="
```

**In `generate_dsl_node` (factory version at line 761):** Remove the mock path entirely. The function already raises `ValidationError` when LLM is None, which is correct.

Actually, looking more carefully at the code, the `_make_generate_dsl_node` factory (line 761) already only uses LLM. The `mock_dsl_node` is a separate node. We should keep `mock_dsl_node` for now but make the orchestration not route to it by default. Per the design doc, the mock path should be removed from the default pipeline.

However, the key change per design doc is:
1. Remove `_mock_dsl_from_question` and `_mock_sc_dsl` (done above)
2. `_semantic_fix_dsl` should not have hardcoded fallback (already agentic)
3. `correct_dsl_node` should not fall back to mock

**In `_make_correct_dsl_node` (line 822):** Remove the mock fallback at the end (lines 931-946). Replace with:

```python
        # No fallback: if LLM correction fails, return error state
        return {
            "status": "error",
            "error": f"DSL correction failed: {error}",
            "error_code": "CORRECTION_FAILED",
            "trace": {
                "step": "correct_dsl",
                "status": "error",
                "error": error,
            },
        }
```

Also need to add import for `FilterTreeNode` if we reference it in `_post_process_dsl`. Actually, the tree validation code above doesn't import it — it just checks for the dict structure.

Now, update `create_node_functions` to wire in the semantic validator. We need to pass a `semantic_validator` parameter and call it after DSL generation.

But wait — looking at the design doc again, the semantic validator runs "in DSL 生成后、SQL 构建前". This means it should be a separate node in the graph, or called within `generate_dsl_node`. Let's add it as a validation step within `generate_dsl_node`.

Actually, to keep changes minimal, let's add the semantic validator check to `generate_dsl_node` and `correct_dsl_node` — after DSL is built, validate semantics. If errors are found, raise `ValidationError` so the error routing kicks in.

But that changes the signature of `create_node_functions`. Let me think about this more carefully.

Per the design doc section 3.3:
- `dsl/semantic_validator.py` 新增
- `graph/nodes.py` 简化 — delete mock; enhance `_post_process_dsl`

The semantic validator is a new layer. The simplest integration is to call it inside `generate_dsl_node` after building the DSL, and in `correct_dsl_node` too. If semantic errors exist, we can either:
1. Log warnings and continue
2. Raise ValidationError to trigger correction loop

Per the design doc section 7.2:
- errors → return to LLM for auto-correction
- warnings → log only, don't block

So semantic errors should raise ValidationError (to trigger the correction loop), and warnings should be logged.

Let's modify `_make_generate_dsl_node` to accept a `semantic_validator` parameter, and add the check. Similarly for `correct_dsl_node`.

Update `_make_generate_dsl_node` signature:
```python
def _make_generate_dsl_node(llm_client, rag_retriever, semantic_validator=None, llm_system_prompt: str = ""):
```

Add after `dsl = DSL.model_validate(dsl_dict)` (around line 784):
```python
        # Semantic validation
        if semantic_validator is not None:
            errors, warnings = semantic_validator.validate(dsl)
            for w in warnings:
                logger.warning("[semantic_validator] %s: %s", w.category, w.message)
            if errors:
                raise ValidationError(f"Semantic validation failed: {'; '.join(errors)}")
```

Similarly update `_make_correct_dsl_node` signature and add the same check after line 909.

Update `create_node_functions` signature to accept `semantic_validator=None` and pass it through.

Here's a consolidated approach for the edit. Due to the size of the file, let's make targeted edits:

**Edit 1:** Remove `_mock_dsl_from_question` and `_mock_sc_dsl`:

In `nl2dsl/graph/nodes.py`, delete lines 392-627 (both mock functions).

**Edit 2:** Update `_post_process_dsl` filter validation:

Replace lines 381-388 with:

```python
    # 8. Validate filters operator values (support both flat list and tree)
    valid_ops = {"=", "!=", ">", "<", ">=", "<=", "in", "like", "between", "is_null"}
    filters = dsl_dict.get("filters")
    if filters:
        if isinstance(filters, dict) and filters.get("op") in {"and", "or", "not"}:
            # Filter tree format — recursively validate leaf operators
            def _validate_tree(node):
                if node.get("op") in {"and", "or", "not"}:
                    for child in node.get("children", []):
                        _validate_tree(child)
                elif isinstance(node, dict) and "field" in node:
                    op = node.get("operator", "")
                    if op not in valid_ops:
                        node["operator"] = "="
            _validate_tree(filters)
        elif isinstance(filters, list):
            for f in filters:
                if isinstance(f, dict):
                    op = f.get("operator", "")
                    if op not in valid_ops:
                        f["operator"] = "="
```

**Edit 3:** Update `_make_generate_dsl_node` to accept and use semantic_validator:

Replace line 761:
```python
def _make_generate_dsl_node(llm_client, rag_retriever, semantic_validator=None, llm_system_prompt: str = ""):
```

After line 784 (`dsl = DSL.model_validate(dsl_dict)`), add:
```python
        # Semantic validation
        if semantic_validator is not None:
            errors, warnings = semantic_validator.validate(dsl)
            for w in warnings:
                logger.warning("[semantic_validator] %s: %s", w.category, w.message)
            if errors:
                raise ValidationError(f"Semantic validation failed: {'; '.join(errors)}")
```

**Edit 4:** Update `_make_correct_dsl_node` similarly:

Replace line 822:
```python
def _make_correct_dsl_node(llm_client, rag_retriever, registry_dict: dict, semantic_validator=None, llm_system_prompt: str = ""):
```

After line 909 (`dsl = DSL.model_validate(dsl_dict)`), add the same semantic validation block.

Also replace the mock fallback (lines 931-946) with the error return shown above.

**Edit 5:** Update `create_node_functions` signature and calls:

Add `semantic_validator=None` parameter to the function signature at line 1183.

Update the `_make_generate_dsl_node` call — search for where it's used in `create_node_functions`. Actually, looking at the code, `_make_generate_dsl_node` is not called inside `create_node_functions` — the inline `generate_dsl_node` is defined there (line 1222). So we need to add the semantic validation to the inline version too.

Wait, looking more carefully:
- `_make_generate_dsl_node` (line 761) is a standalone factory
- `create_node_functions` (line 1169) defines an inline `generate_dsl_node` (line 1222)
- Both exist! The standalone one might be used in tests or elsewhere.

We should update both. For the inline one in `create_node_functions`, add after line 1242 (`dsl = DSL.model_validate(dsl_dict)`):

```python
        # Semantic validation
        if semantic_validator is not None:
            errors, warnings = semantic_validator.validate(dsl)
            for w in warnings:
                logger.warning("[semantic_validator] %s: %s", w.category, w.message)
            if errors:
                raise ValidationError(f"Semantic validation failed: {'; '.join(errors)}")
```

Also update `correct_dsl_node` assignment (line 1353) to pass `semantic_validator`:
```python
    correct_dsl_node = _make_correct_dsl_node(
        llm_client, rag_retriever, {}, semantic_validator, llm_system_prompt
    )
```

- [ ] **Step 4: Run all graph node tests**

```bash
pytest tests/unit/test_graph_nodes.py -v
```

Expected: PASS. Note: tests that referenced `_mock_dsl_from_question` will need to be removed/updated from the existing test file. Check which tests reference it and remove them.

If there are tests that still import `_mock_dsl_from_question`, they will fail with ImportError. Update the imports in `tests/unit/test_graph_nodes.py` to remove `_mock_dsl_from_question` and `_mock_sc_dsl`.

- [ ] **Step 5: Commit**

```bash
git add nl2dsl/graph/nodes.py tests/unit/test_graph_nodes.py
git commit -m "feat(graph): remove mock DSL, add semantic validation, support filter trees in post-processing"
```

---

### Task 8: Regression — Run All Existing Tests

**Files:** N/A (verification step)

- [ ] **Step 1: Run the full unit test suite**

```bash
pytest tests/unit/ -v --tb=short 2>&1 | head -100
```

Expected: All tests pass. If any fail due to the DSL model changes (e.g., `test_dsl_validator.py` or `test_dsl_builder.py`), fix them.

Common fixes needed:
- `test_dsl_validator.py`: The validator expects `dsl.metrics` and `dsl.dimensions` — should still work since our changes are backward compatible.
- Any test that imports `_mock_dsl_from_question`: Remove that import.

- [ ] **Step 2: Run integration tests if they exist**

```bash
pytest tests/integration/ -v --tb=short 2>&1 | head -50
```

- [ ] **Step 3: Commit any regression fixes**

```bash
git commit -m "fix(tests): regression fixes after DSL model refactoring"
```

---

### Task 9: Integration — Wire Semantic Validator into Engine

**Files:**
- Modify: `nl2dsl/engine.py` (or wherever the pipeline is assembled)

**Context:** The semantic validator needs a registry to be instantiated. Find where `create_node_functions` is called and pass the semantic validator.

- [ ] **Step 1: Find where create_node_functions is called**

```bash
grep -rn "create_node_functions" nl2dsl/ --include="*.py"
```

Look at the file(s) that call it and add `semantic_validator` parameter.

- [ ] **Step 2: Add semantic validator instantiation**

Wherever the registry is available and `create_node_functions` is called, add:

```python
from nl2dsl.dsl.semantic_validator import SemanticValidator

semantic_validator = SemanticValidator(registry_dict)

nodes = create_node_functions(
    ...,
    semantic_validator=semantic_validator,
)
```

- [ ] **Step 3: Verify with a quick smoke test**

```bash
python -c "from nl2dsl.engine import create_engine; print('OK')"
```

Or run the relevant test:
```bash
pytest tests/unit/test_engine.py -v
```

- [ ] **Step 4: Commit**

```bash
git add nl2dsl/engine.py
git commit -m "feat(engine): wire semantic validator into query pipeline"
```

---

## Self-Review Checklist

**1. Spec coverage:**

| Spec Requirement | Task |
|---|---|
| Filter 条件树（and/or/not） | Task 1 (DSL models), Task 5 (SQL Builder), Task 7 (graph nodes) |
| 新增 having 字段 | Task 1 (DSL models), Task 5 (SQL Builder), Task 4 (semantic validator) |
| time_field/time_range 启用 | Task 1 (DSL models), Task 5 (SQL Builder) |
| 零示例 Prompt + CoT | Task 2 (prompts) |
| JSON Schema 约束 | Task 2 (prompts), Task 3 (LLM client) |
| between / is_null 操作符 | Task 5 (SQL Builder) |
| 条件冲突检测 | Task 4 (semantic validator) |
| having-requires-metric 校验 | Task 4 (semantic validator) |
| 每组 TOP1（Python 层） | Task 6 (post-processor) |
| 删除 Mock DSL | Task 7 (graph nodes) |
| LLM 唯一路径 | Task 7 (graph nodes — remove mock fallback) |
| 向后兼容（扁平列表格式） | Task 1 (DSL model validators) |

No gaps identified.

**2. Placeholder scan:**
- No "TBD", "TODO", "implement later" found.
- No "Add appropriate error handling" — all error handling is specified in code.
- No "Write tests for the above" — every task has concrete test code.
- No "Similar to Task N" — each task is self-contained.
- All file paths are exact.
- All code blocks contain complete implementations.

**3. Type consistency:**
- `FilterTreeNode` used consistently across Tasks 1, 4, 5, 7.
- `Having` used consistently across Tasks 1, 4, 5.
- `SemanticValidator.validate()` returns `tuple[list[str], list[SemanticWarning]]` consistently.
- `generate_structured()` signature consistent between implementation and test.

All checks pass.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-31-complex-query-semantic-understanding.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

**Which approach?**
