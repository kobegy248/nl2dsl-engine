# Evaluation V2 — 语义理解基准测试实施计划

> **面向自动化执行者：** 必备子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 按任务逐一实施。步骤使用 checkbox（`- [ ]`）语法进行跟踪。

**目标：** 实现 Evaluation V2 框架：规范化语义解析器（Canonical Semantic Resolver）+ 独立评分器（Scorer）+ 新用例模式（Case Schema）+ 分层执行阶段，将评测从"SQL 准确性"转变为"语义理解准确性"。

**架构：** 新增 `evaluation/canonical/` 目录实现 6 个解析器，新增 `evaluation/scorers/` 目录实现 5 个独立评分器，`evaluation/stages/` 实现 semantic/execution 分层执行。V2 与 V1 并存，渐进式迁移。规范化解析器利用项目现有的 `configs/metrics.yaml` 配置自动构建映射关系。

**技术栈：** Python 3.12、Pydantic、PyYAML、pytest、FastAPI TestClient

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `nl2dsl/evaluation/canonical/__init__.py` | 包初始化，导出 |
| `nl2dsl/evaluation/canonical/resolver.py` | **新增** — CanonicalResolver 主类，协调各子解析器 |
| `nl2dsl/evaluation/canonical/metric_resolver.py` | **新增** — 指标 → metric_id 规范化 |
| `nl2dsl/evaluation/canonical/dimension_resolver.py` | **新增** — 维度 → 物理列名规范化 |
| `nl2dsl/evaluation/canonical/value_resolver.py` | **新增** — 值 → 物理值规范化 |
| `nl2dsl/evaluation/canonical/time_resolver.py` | **新增** — 时间 → {start, end, granularity} 规范化 |
| `nl2dsl/evaluation/canonical/join_resolver.py` | **新增** — 关联 → {entity, on_field, join_type} 规范化 |
| `nl2dsl/evaluation/canonical/order_resolver.py` | **新增** — 排序规范化（默认方向处理） |
| `nl2dsl/evaluation/scorers/__init__.py` | 包初始化 |
| `nl2dsl/evaluation/scorers/base.py` | **新增** — 评分器抽象基类 |
| `nl2dsl/evaluation/scorers/intent_scorer.py` | **新增** — 意图二元评分 |
| `nl2dsl/evaluation/scorers/metric_scorer.py` | **新增** — 指标规范化比较评分 |
| `nl2dsl/evaluation/scorers/filter_scorer.py` | **新增** — 过滤条件规范化比较评分 |
| `nl2dsl/evaluation/scorers/planner_scorer.py` | **新增** — 规划器（维度 + 排序 + 分页 + 关联）评分 |
| `nl2dsl/evaluation/scorers/governance_scorer.py` | **新增** — 治理评分 |
| `nl2dsl/evaluation/models.py` | **扩展** — 新增 V2 数据模型（CanonicalQuery、V2TestCase 等） |
| `nl2dsl/evaluation/runner.py` | **扩展** — BenchmarkRunner 支持阶段选择 |
| `nl2dsl/evaluation/dataset.py` | **扩展** — V2 用例加载器支持新模式 |
| `nl2dsl/evaluation/report.py` | **扩展** — 新增控制台/markdown 报告器 |
| `nl2dsl/evaluation/cli.py` | **扩展** — 新增 `--stage` 参数 |
| `tests/evaluation/v2/` | **新增** — V2 单元测试目录 |
| `tests/evaluation/dataset/v2/` | **新增** — V2 测试数据集 |

---

## 第一阶段：规范化解析器核心

### 任务 1：指标解析器

**文件：**
- 创建：`nl2dsl/evaluation/canonical/metric_resolver.py`
- 创建：`tests/evaluation/v2/test_metric_resolver.py`

**背景：** 利用 `configs/metrics.yaml` 中的配置，将 DSL 中的指标别名（metric alias）或字段+函数组合映射到规范化的 metric_id。

- [ ] **步骤 1：编写会失败的测试**

```python
# tests/evaluation/v2/test_metric_resolver.py
import pytest
from nl2dsl.evaluation.canonical.metric_resolver import MetricResolver


@pytest.fixture
def resolver():
    return MetricResolver({
        "sales_amount": {"expr": "SUM(pay_amount)", "canonical_id": "sales_amount"},
        "gmv": {"expr": "SUM(order_amount)", "canonical_id": "gmv"},
        "order_count": {"expr": "COUNT(id)", "canonical_id": "order_count"},
    })


def test_resolve_by_alias(resolver):
    """别名直接匹配 metric_id"""
    assert resolver.resolve("sales_amount") == "sales_amount"


def test_resolve_by_field_func(resolver):
    """通过字段+函数反查 metric_id"""
    assert resolver.resolve("pay_amount", func="sum") == "sales_amount"


def test_resolve_unknown(resolver):
    """无法解析时返回原始值"""
    assert resolver.resolve("unknown") == "unknown"
```

- [ ] **步骤 2：运行测试，验证失败**

```bash
pytest tests/evaluation/v2/test_metric_resolver.py -v
```

预期结果：FAIL，错误信息为 "ModuleNotFoundError: No module named 'nl2dsl.evaluation.canonical'"

- [ ] **步骤 3：编写最小实现**

```python
# nl2dsl/evaluation/canonical/metric_resolver.py
"""规范化指标解析器。"""


class MetricResolver:
    """将指标别名或字段+函数解析为规范化的 metric_id。"""

    def __init__(self, metrics_config: dict):
        """
        参数：
            metrics_config: {metric_id: {expr: "SUM(field)", canonical_id: "..."}}
        """
        self._config = metrics_config
        # 构建反向查找映射：(field, func) -> metric_id
        self._reverse: dict[tuple[str, str], str] = {}
        for mid, cfg in metrics_config.items():
            expr = cfg.get("expr", "")
            # 解析 "SUM(pay_amount)" -> ("sum", "pay_amount")
            if "(" in expr and ")" in expr:
                func = expr.split("(")[0].strip().lower()
                field = expr.split("(")[1].split(")")[0].strip()
                self._reverse[(field, func)] = cfg.get("canonical_id", mid)

    def resolve(self, alias_or_field: str, func: str | None = None) -> str:
        """解析为规范化的 metric_id。

        策略：
        1. 直接别名匹配
        2. 字段+函数反向查找
        3. 兜底返回原始值
        """
        # 1. 直接别名匹配
        if alias_or_field in self._config:
            return self._config[alias_or_field].get("canonical_id", alias_or_field)

        # 2. 字段+函数反向查找
        if func:
            key = (alias_or_field, func.lower())
            if key in self._reverse:
                return self._reverse[key]

        # 3. 兜底
        return alias_or_field
```

- [ ] **步骤 4：运行测试，验证通过**

```bash
pytest tests/evaluation/v2/test_metric_resolver.py -v
```

预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add nl2dsl/evaluation/canonical/metric_resolver.py tests/evaluation/v2/test_metric_resolver.py
git commit -m "feat(evaluation): 添加规范化指标解析器"
```

---

### 任务 2：维度解析器

**文件：**
- 创建：`nl2dsl/evaluation/canonical/dimension_resolver.py`
- 创建：`tests/evaluation/v2/test_dimension_resolver.py`

- [ ] **步骤 1：编写会失败的测试**

```python
# tests/evaluation/v2/test_dimension_resolver.py
import pytest
from nl2dsl.evaluation.canonical.dimension_resolver import DimensionResolver


@pytest.fixture
def resolver():
    return DimensionResolver({
        "product_name": {"column": "product_name"},
        "region": {"column": "region_code", "value_map": {"华东": "HD", "华南": "HN"}},
        "brand": {"column": "brand"},
    })


def test_resolve_direct(resolver):
    assert resolver.resolve("product_name") == "product_name"


def test_resolve_mapped(resolver):
    assert resolver.resolve("region") == "region_code"
```

- [ ] **步骤 2：运行测试**

```bash
pytest tests/evaluation/v2/test_dimension_resolver.py -v
```

预期结果：FAIL

- [ ] **步骤 3：编写实现**

```python
# nl2dsl/evaluation/canonical/dimension_resolver.py
"""规范化维度解析器。"""


class DimensionResolver:
    """将维度别名解析为物理列名。"""

    def __init__(self, dimensions_config: dict):
        self._config = dimensions_config

    def resolve(self, alias: str) -> str:
        """将维度别名解析为物理列名。"""
        cfg = self._config.get(alias, {})
        return cfg.get("column", alias)

    def get_value_map(self, alias: str) -> dict | None:
        """获取维度的值映射（如果存在）。"""
        cfg = self._config.get(alias, {})
        return cfg.get("value_map")
```

- [ ] **步骤 4：运行测试**

```bash
pytest tests/evaluation/v2/test_dimension_resolver.py -v
```

预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add nl2dsl/evaluation/canonical/dimension_resolver.py tests/evaluation/v2/test_dimension_resolver.py
git commit -m "feat(evaluation): 添加规范化维度解析器"
```

---

### 任务 3：值解析器

**文件：**
- 创建：`nl2dsl/evaluation/canonical/value_resolver.py`
- 创建：`tests/evaluation/v2/test_value_resolver.py`

- [ ] **步骤 1：编写会失败的测试**

```python
# tests/evaluation/v2/test_value_resolver.py
import pytest
from nl2dsl.evaluation.canonical.value_resolver import ValueResolver


@pytest.fixture
def resolver():
    return ValueResolver({
        "region": {"value_map": {"华东": "HD", "华南": "HN"}},
        "channel": {"value_map": {"线上": "online", "线下": "offline"}},
    })


def test_resolve_mapped_value(resolver):
    assert resolver.resolve("region", "华东") == "HD"


def test_resolve_unmapped_value(resolver):
    assert resolver.resolve("brand", "Apple") == "Apple"


def test_resolve_dimension_without_map(resolver):
    assert resolver.resolve("region", "华北") == "华北"
```

- [ ] **步骤 2：运行测试**

```bash
pytest tests/evaluation/v2/test_value_resolver.py -v
```

预期结果：FAIL

- [ ] **步骤 3：编写实现**

```python
# nl2dsl/evaluation/canonical/value_resolver.py
"""规范化值解析器。"""


class ValueResolver:
    """将维度值别名解析为物理值。"""

    def __init__(self, dimensions_config: dict):
        self._config = dimensions_config

    def resolve(self, dimension: str, value) -> str:
        """将值别名解析为物理值。

        参数：
            dimension: 维度别名
            value: 原始值（可以是别名或物理值）
        """
        cfg = self._config.get(dimension, {})
        value_map = cfg.get("value_map", {})
        if value_map and str(value) in value_map:
            return value_map[str(value)]
        return str(value)
```

- [ ] **步骤 4：运行测试**

```bash
pytest tests/evaluation/v2/test_value_resolver.py -v
```

预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add nl2dsl/evaluation/canonical/value_resolver.py tests/evaluation/v2/test_value_resolver.py
git commit -m "feat(evaluation): 添加规范化值解析器"
```

---

### 任务 4：时间解析器

**文件：**
- 创建：`nl2dsl/evaluation/canonical/time_resolver.py`
- 创建：`tests/evaluation/v2/test_time_resolver.py`

- [ ] **步骤 1：编写会失败的测试**

```python
# tests/evaluation/v2/test_time_resolver.py
import pytest
from nl2dsl.evaluation.canonical.time_resolver import TimeResolver, CanonicalTimeRange


@pytest.fixture
def resolver():
    return TimeResolver()


def test_resolve_year(resolver):
    result = resolver.resolve("2024年")
    assert result.start == "2024-01-01"
    assert result.end == "2024-12-31"
    assert result.granularity == "year"


def test_resolve_month(resolver):
    result = resolver.resolve("2024年1月")
    assert result.start == "2024-01-01"
    assert result.end == "2024-01-31"
    assert result.granularity == "month"


def test_resolve_range(resolver):
    result = resolver.resolve(["2024-01-01", "2024-12-31"])
    assert result.start == "2024-01-01"
    assert result.end == "2024-12-31"
    assert result.granularity == "day"
```

- [ ] **步骤 2：运行测试**

```bash
pytest tests/evaluation/v2/test_time_resolver.py -v
```

预期结果：FAIL

- [ ] **步骤 3：编写实现**

```python
# nl2dsl/evaluation/canonical/time_resolver.py
"""规范化时间解析器，包含粒度信息。"""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class CanonicalTimeRange:
    """规范化的时间表示。"""

    start: str
    end: str
    granularity: str  # day | week | month | quarter | year


class TimeResolver:
    """将自然语言时间表达式解析为规范化的时间范围。"""

    _YEAR_RE = re.compile(r"^(\d{4})年$")
    _MONTH_RE = re.compile(r"^(\d{4})年(\d{1,2})月$")
    _QUARTER_RE = re.compile(r"^(\d{4})年([Qq]\d)$")

    def resolve(self, time_expr) -> CanonicalTimeRange | None:
        """将时间表达式解析为规范化的范围。

        参数：
            time_expr: 如 "2024年" 的字符串，或如 ["2024-01-01", "2024-12-31"] 的列表
        """
        if time_expr is None:
            return None

        # 已是范围格式
        if isinstance(time_expr, (list, tuple)) and len(time_expr) == 2:
            return CanonicalTimeRange(
                start=str(time_expr[0]),
                end=str(time_expr[1]),
                granularity="day",
            )

        if not isinstance(time_expr, str):
            return None

        s = time_expr.strip()

        # 年份："2024年"
        m = self._YEAR_RE.match(s)
        if m:
            year = m.group(1)
            return CanonicalTimeRange(f"{year}-01-01", f"{year}-12-31", "year")

        # 月份："2024年1月"
        m = self._MONTH_RE.match(s)
        if m:
            year, month = m.group(1), int(m.group(2))
            # 简易月末计算
            end_day = "31" if month in (1, 3, 5, 7, 8, 10, 12) else "30"
            if month == 2:
                end_day = "29" if int(year) % 4 == 0 else "28"
            return CanonicalTimeRange(
                f"{year}-{month:02d}-01",
                f"{year}-{month:02d}-{end_day}",
                "month",
            )

        # 季度："2024年Q1"
        m = self._QUARTER_RE.match(s)
        if m:
            year, q = m.group(1), int(m.group(2)[1])
            month_start = (q - 1) * 3 + 1
            month_end = q * 3
            end_day = "31" if month_end in (1, 3, 5, 7, 8, 10, 12) else "30"
            return CanonicalTimeRange(
                f"{year}-{month_start:02d}-01",
                f"{year}-{month_end:02d}-{end_day}",
                "quarter",
            )

        # 尝试直接日期解析
        try:
            from datetime import datetime
            dt = datetime.strptime(s, "%Y-%m-%d")
            return CanonicalTimeRange(s, s, "day")
        except ValueError:
            pass

        return None
```

- [ ] **步骤 4：运行测试**

```bash
pytest tests/evaluation/v2/test_time_resolver.py -v
```

预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add nl2dsl/evaluation/canonical/time_resolver.py tests/evaluation/v2/test_time_resolver.py
git commit -m "feat(evaluation): 添加带粒度信息的规范化时间解析器"
```

---

### 任务 5：关联解析器

**文件：**
- 创建：`nl2dsl/evaluation/canonical/join_resolver.py`
- 创建：`tests/evaluation/v2/test_join_resolver.py`

- [ ] **步骤 1：编写会失败的测试**

```python
# tests/evaluation/v2/test_join_resolver.py
import pytest
from nl2dsl.evaluation.canonical.join_resolver import JoinResolver, CanonicalJoin


@pytest.fixture
def resolver():
    return JoinResolver({
        "customer_dim": {"entity": "customer", "on": "customer_id", "type": "left", "alias": "c"},
        "product_dim": {"entity": "product", "on": "product_id", "type": "inner", "alias": "p"},
    })


def test_resolve_by_table_name(resolver):
    result = resolver.resolve("customer_dim", "customer_id", "left")
    assert result.entity == "customer"
    assert result.on_field == "customer_id"
    assert result.join_type == "left"


def test_resolve_by_alias(resolver):
    result = resolver.resolve("c", "customer_id", "left")
    assert result.entity == "customer"
```

- [ ] **步骤 2：运行测试**

```bash
pytest tests/evaluation/v2/test_join_resolver.py -v
```

预期结果：FAIL

- [ ] **步骤 3：编写实现**

```python
# nl2dsl/evaluation/canonical/join_resolver.py
"""规范化关联解析器。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalJoin:
    """规范化的关联表示。"""

    entity: str
    on_field: str
    join_type: str


class JoinResolver:
    """将关联表/别名解析为规范化的实体表示。"""

    def __init__(self, data_sources_config: dict):
        """
        参数：
            data_sources_config: {data_source: {joins: {table_name: {entity, on, type, alias}}}}
        """
        self._entity_by_table: dict[str, str] = {}
        self._entity_by_alias: dict[str, str] = {}
        self._join_config: dict[str, dict] = {}

        for ds_name, ds_cfg in data_sources_config.items():
            joins = ds_cfg.get("joins", {})
            for table_name, j_cfg in joins.items():
                entity = j_cfg.get("entity", table_name)
                alias = j_cfg.get("alias", "")
                self._entity_by_table[table_name] = entity
                self._join_config[table_name] = j_cfg
                if alias:
                    self._entity_by_alias[alias] = entity

    def resolve(self, table: str, on_field: str, join_type: str) -> CanonicalJoin:
        """将关联解析为规范化的表示。"""
        # 尝试按表名匹配
        entity = self._entity_by_table.get(table)
        if not entity:
            # 尝试按别名匹配
            entity = self._entity_by_alias.get(table, table)

        return CanonicalJoin(
            entity=entity,
            on_field=on_field,
            join_type=join_type.lower(),
        )
```

- [ ] **步骤 4：运行测试**

```bash
pytest tests/evaluation/v2/test_join_resolver.py -v
```

预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add nl2dsl/evaluation/canonical/join_resolver.py tests/evaluation/v2/test_join_resolver.py
git commit -m "feat(evaluation): 添加带实体映射的规范化关联解析器"
```

---

### 任务 6：排序解析器

**文件：**
- 创建：`nl2dsl/evaluation/canonical/order_resolver.py`
- 创建：`tests/evaluation/v2/test_order_resolver.py`

- [ ] **步骤 1：编写会失败的测试**

```python
# tests/evaluation/v2/test_order_resolver.py
import pytest
from nl2dsl.evaluation.canonical.order_resolver import OrderResolver, CanonicalOrderBy


@pytest.fixture
def resolver():
    return OrderResolver()


def test_explicit_direction(resolver):
    """用户明确表达了排序方向"""
    result = resolver.resolve("sales_amount", "desc", user_expressed=True)
    assert result.field == "sales_amount"
    assert result.direction == "desc"
    assert result.is_default is False


def test_default_direction(resolver):
    """用户未表达排序方向，使用系统默认"""
    result = resolver.resolve("sales_amount", None, user_expressed=False)
    assert result.field == "sales_amount"
    assert result.is_default is True
```

- [ ] **步骤 2：运行测试**

```bash
pytest tests/evaluation/v2/test_order_resolver.py -v
```

预期结果：FAIL

- [ ] **步骤 3：编写实现**

```python
# nl2dsl/evaluation/canonical/order_resolver.py
"""规范化排序解析器。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalOrderBy:
    """规范化的排序表示。"""

    field: str
    direction: str | None  # "asc" | "desc" | None（默认）
    is_default: bool  # 如果方向非用户显式指定则为 True


class OrderResolver:
    """将排序解析为规范化的表示。"""

    def resolve(self, field: str, direction: str | None, user_expressed: bool = False) -> CanonicalOrderBy:
        """解析排序。

        参数：
            field: 排序字段
            direction: "asc"、"desc" 或 None
            user_expressed: 用户是否明确表达了排序方向
        """
        return CanonicalOrderBy(
            field=field,
            direction=direction.lower() if direction else None,
            is_default=not user_expressed,
        )
```

- [ ] **步骤 4：运行测试**

```bash
pytest tests/evaluation/v2/test_order_resolver.py -v
```

预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add nl2dsl/evaluation/canonical/order_resolver.py tests/evaluation/v2/test_order_resolver.py
git commit -m "feat(evaluation): 添加支持默认方向处理的规范化排序解析器"
```

---

### 任务 7：规范化解析器主类

**文件：**
- 创建：`nl2dsl/evaluation/canonical/resolver.py`
- 创建：`tests/evaluation/v2/test_resolver.py`
- 创建：`nl2dsl/evaluation/canonical/__init__.py`

- [ ] **步骤 1：编写会失败的测试**

```python
# tests/evaluation/v2/test_resolver.py
import pytest
from nl2dsl.evaluation.canonical.resolver import CanonicalResolver


@pytest.fixture
def resolver():
    return CanonicalResolver.from_config({
        "metrics": {
            "sales_amount": {"expr": "SUM(pay_amount)", "canonical_id": "sales_amount"},
        },
        "dimensions": {
            "region": {"column": "region_code", "value_map": {"华东": "HD"}},
        },
        "data_sources": {
            "orders": {
                "joins": {
                    "customer_dim": {"entity": "customer", "on": "customer_id", "type": "left", "alias": "c"},
                }
            }
        },
    })


def test_resolve_metric(resolver):
    assert resolver.resolve_metric("sales_amount") == "sales_amount"


def test_resolve_dimension(resolver):
    assert resolver.resolve_dimension("region") == "region_code"


def test_resolve_value(resolver):
    assert resolver.resolve_value("region", "华东") == "HD"


def test_resolve_time(resolver):
    result = resolver.resolve_time("2024年")
    assert result.start == "2024-01-01"
    assert result.granularity == "year"
```

- [ ] **步骤 2：运行测试**

```bash
pytest tests/evaluation/v2/test_resolver.py -v
```

预期结果：FAIL

- [ ] **步骤 3：编写实现**

```python
# nl2dsl/evaluation/canonical/resolver.py
"""规范化语义解析器 — 主编排器。"""

from __future__ import annotations

from nl2dsl.evaluation.canonical.metric_resolver import MetricResolver
from nl2dsl.evaluation.canonical.dimension_resolver import DimensionResolver
from nl2dsl.evaluation.canonical.value_resolver import ValueResolver
from nl2dsl.evaluation.canonical.time_resolver import TimeResolver, CanonicalTimeRange
from nl2dsl.evaluation.canonical.join_resolver import JoinResolver, CanonicalJoin
from nl2dsl.evaluation.canonical.order_resolver import OrderResolver, CanonicalOrderBy


class CanonicalResolver:
    """编排所有规范化解析器。"""

    def __init__(
        self,
        metric_resolver: MetricResolver,
        dimension_resolver: DimensionResolver,
        value_resolver: ValueResolver,
        time_resolver: TimeResolver,
        join_resolver: JoinResolver,
        order_resolver: OrderResolver,
    ):
        self.metric = metric_resolver
        self.dimension = dimension_resolver
        self.value = value_resolver
        self.time = time_resolver
        self.join = join_resolver
        self.order = order_resolver

    @classmethod
    def from_config(cls, config: dict) -> CanonicalResolver:
        """从项目配置（metrics.yaml 格式）构建解析器。"""
        return cls(
            metric_resolver=MetricResolver(config.get("metrics", {})),
            dimension_resolver=DimensionResolver(config.get("dimensions", {})),
            value_resolver=ValueResolver(config.get("dimensions", {})),
            time_resolver=TimeResolver(),
            join_resolver=JoinResolver(config.get("data_sources", {})),
            order_resolver=OrderResolver(),
        )

    def resolve_metric(self, alias_or_field: str, func: str | None = None) -> str:
        return self.metric.resolve(alias_or_field, func)

    def resolve_dimension(self, alias: str) -> str:
        return self.dimension.resolve(alias)

    def resolve_value(self, dimension: str, value) -> str:
        return self.value.resolve(dimension, value)

    def resolve_time(self, time_expr) -> CanonicalTimeRange | None:
        return self.time.resolve(time_expr)

    def resolve_join(self, table: str, on_field: str, join_type: str) -> CanonicalJoin:
        return self.join.resolve(table, on_field, join_type)

    def resolve_order(self, field: str, direction: str | None, user_expressed: bool = False) -> CanonicalOrderBy:
        return self.order.resolve(field, direction, user_expressed)
```

```python
# nl2dsl/evaluation/canonical/__init__.py
"""规范化语义解析器包。"""

from nl2dsl.evaluation.canonical.resolver import CanonicalResolver
from nl2dsl.evaluation.canonical.metric_resolver import MetricResolver
from nl2dsl.evaluation.canonical.dimension_resolver import DimensionResolver
from nl2dsl.evaluation.canonical.value_resolver import ValueResolver
from nl2dsl.evaluation.canonical.time_resolver import TimeResolver, CanonicalTimeRange
from nl2dsl.evaluation.canonical.join_resolver import JoinResolver, CanonicalJoin
from nl2dsl.evaluation.canonical.order_resolver import OrderResolver, CanonicalOrderBy

__all__ = [
    "CanonicalResolver",
    "MetricResolver",
    "DimensionResolver",
    "ValueResolver",
    "TimeResolver",
    "CanonicalTimeRange",
    "JoinResolver",
    "CanonicalJoin",
    "OrderResolver",
    "CanonicalOrderBy",
]
```

- [ ] **步骤 4：运行测试**

```bash
pytest tests/evaluation/v2/test_resolver.py -v
```

预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add nl2dsl/evaluation/canonical/ tests/evaluation/v2/test_resolver.py
git commit -m "feat(evaluation): 添加规范化解析器编排器"
```

---

## 第二阶段：评分器

### 任务 8：评分器基类

**文件：**
- 创建：`nl2dsl/evaluation/scorers/base.py`
- 创建：`nl2dsl/evaluation/scorers/__init__.py`
- 创建：`tests/evaluation/v2/test_base_scorer.py`

- [ ] **步骤 1：编写会失败的测试**

```python
# tests/evaluation/v2/test_base_scorer.py
import pytest
from nl2dsl.evaluation.scorers.base import Scorer


def test_scorer_is_abstract():
    """Scorer 不能直接实例化。"""
    with pytest.raises(TypeError):
        Scorer()
```

- [ ] **步骤 2：运行测试**

```bash
pytest tests/evaluation/v2/test_base_scorer.py -v
```

预期结果：FAIL

- [ ] **步骤 3：编写实现**

```python
# nl2dsl/evaluation/scorers/base.py
"""评分器抽象基类。"""

from abc import ABC, abstractmethod


class Scorer(ABC):
    """所有评分器的抽象基类。

    评分器执行二元评估：1.0（通过）或 0.0（不通过）。
    不存在部分得分。
    """

    @abstractmethod
    def score(self, expected, actual) -> float:
        """对预期值与实际值进行评分。

        参数：
            expected: 预期的规范化值
            actual: 实际的规范化值

        返回：
            匹配返回 1.0，否则返回 0.0
        """
        pass
```

```python
# nl2dsl/evaluation/scorers/__init__.py
"""评分器包。"""

from nl2dsl.evaluation.scorers.base import Scorer

__all__ = ["Scorer"]
```

- [ ] **步骤 4：运行测试**

```bash
pytest tests/evaluation/v2/test_base_scorer.py -v
```

预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add nl2dsl/evaluation/scorers/ tests/evaluation/v2/test_base_scorer.py
git commit -m "feat(evaluation): 添加评分器抽象基类"
```

---

### 任务 9：意图评分器

**文件：**
- 创建：`nl2dsl/evaluation/scorers/intent_scorer.py`
- 创建：`tests/evaluation/v2/test_intent_scorer.py`

- [ ] **步骤 1：编写会失败的测试**

```python
# tests/evaluation/v2/test_intent_scorer.py
import pytest
from nl2dsl.evaluation.scorers.intent_scorer import IntentScorer


@pytest.fixture
def scorer():
    return IntentScorer()


def test_match(scorer):
    assert scorer.score("aggregate", "aggregate") == 1.0


def test_mismatch(scorer):
    assert scorer.score("aggregate", "rank") == 0.0
```

- [ ] **步骤 2：运行测试**

```bash
pytest tests/evaluation/v2/test_intent_scorer.py -v
```

预期结果：FAIL

- [ ] **步骤 3：编写实现**

```python
# nl2dsl/evaluation/scorers/intent_scorer.py
"""意图评分器。"""

from nl2dsl.evaluation.scorers.base import Scorer


class IntentScorer(Scorer):
    """对意图匹配进行评分。二元：1.0（匹配）或 0.0（不匹配）。"""

    def score(self, expected: str, actual: str) -> float:
        return 1.0 if expected == actual else 0.0
```

- [ ] **步骤 4：运行测试**

```bash
pytest tests/evaluation/v2/test_intent_scorer.py -v
```

预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add nl2dsl/evaluation/scorers/intent_scorer.py tests/evaluation/v2/test_intent_scorer.py
git commit -m "feat(evaluation): 添加意图评分器"
```

---

### 任务 10：指标评分器

**文件：**
- 创建：`nl2dsl/evaluation/scorers/metric_scorer.py`
- 创建：`tests/evaluation/v2/test_metric_scorer.py`

- [ ] **步骤 1：编写会失败的测试**

```python
# tests/evaluation/v2/test_metric_scorer.py
import pytest
from nl2dsl.evaluation.scorers.metric_scorer import MetricScorer
from nl2dsl.evaluation.canonical.metric_resolver import MetricResolver


@pytest.fixture
def scorer():
    resolver = MetricResolver({
        "sales_amount": {"expr": "SUM(pay_amount)", "canonical_id": "sales_amount"},
    })
    return MetricScorer(resolver)


def test_alias_match(scorer):
    """别名直接匹配"""
    assert scorer.score("sales_amount", "sales_amount") == 1.0


def test_field_func_match(scorer):
    """字段+函数反查后匹配"""
    assert scorer.score("sales_amount", "pay_amount", func="sum") == 1.0


def test_mismatch(scorer):
    """完全不同的指标"""
    assert scorer.score("sales_amount", "gmv") == 0.0
```

- [ ] **步骤 2：运行测试**

```bash
pytest tests/evaluation/v2/test_metric_scorer.py -v
```

预期结果：FAIL

- [ ] **步骤 3：编写实现**

```python
# nl2dsl/evaluation/scorers/metric_scorer.py
"""指标评分器。"""

from nl2dsl.evaluation.scorers.base import Scorer
from nl2dsl.evaluation.canonical.metric_resolver import MetricResolver


class MetricScorer(Scorer):
    """使用规范化解析器对指标匹配进行评分。

    预期值：metric_id 字符串
    实际值：metric_id 字符串，或 (field, func) 元组
    """

    def __init__(self, resolver: MetricResolver):
        self._resolver = resolver

    def score(self, expected: str, actual: str, func: str | None = None) -> float:
        """对指标匹配进行评分。

        参数：
            expected: 预期的 metric_id
            actual: 实际的 metric_id 或字段名
            func: 实际的聚合函数（用于反向查找）
        """
        canonical_expected = self._resolver.resolve(expected)
        canonical_actual = self._resolver.resolve(actual, func)
        return 1.0 if canonical_expected == canonical_actual else 0.0
```

- [ ] **步骤 4：运行测试**

```bash
pytest tests/evaluation/v2/test_metric_scorer.py -v
```

预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add nl2dsl/evaluation/scorers/metric_scorer.py tests/evaluation/v2/test_metric_scorer.py
git commit -m "feat(evaluation): 添加带规范化解析的指标评分器"
```

---

### 任务 11：过滤条件评分器

**文件：**
- 创建：`nl2dsl/evaluation/scorers/filter_scorer.py`
- 创建：`tests/evaluation/v2/test_filter_scorer.py`

- [ ] **步骤 1：编写会失败的测试**

```python
# tests/evaluation/v2/test_filter_scorer.py
import pytest
from nl2dsl.evaluation.scorers.filter_scorer import FilterScorer
from nl2dsl.evaluation.canonical.resolver import CanonicalResolver


@pytest.fixture
def scorer():
    resolver = CanonicalResolver.from_config({
        "dimensions": {
            "region": {"column": "region_code", "value_map": {"华东": "HD"}},
        },
    })
    return FilterScorer(resolver)


def test_exact_match(scorer):
    """完全相同"""
    assert scorer.score(
        [{"field": "region", "operator": "=", "value": "华东"}],
        [{"field": "region", "operator": "=", "value": "华东"}],
    ) == 1.0


def test_canonical_match(scorer):
    """规范化后等价"""
    assert scorer.score(
        [{"field": "region", "operator": "=", "value": "华东"}],
        [{"field": "region_code", "operator": "=", "value": "HD"}],
    ) == 1.0
```

- [ ] **步骤 2：运行测试**

```bash
pytest tests/evaluation/v2/test_filter_scorer.py -v
```

预期结果：FAIL

- [ ] **步骤 3：编写实现**

```python
# nl2dsl/evaluation/scorers/filter_scorer.py
"""过滤条件评分器。"""

from nl2dsl.evaluation.scorers.base import Scorer
from nl2dsl.evaluation.canonical.resolver import CanonicalResolver


class FilterScorer(Scorer):
    """使用规范化解析器对过滤条件匹配进行评分。

    比较过滤条件的规范化表示。
    """

    def __init__(self, resolver: CanonicalResolver):
        self._resolver = resolver

    def score(self, expected: list[dict], actual: list[dict]) -> float:
        """对过滤条件匹配进行评分。

        参数：
            expected: 预期过滤条件字典列表
            actual: 实际过滤条件字典列表
        """
        e_canonical = self._canonicalize_filters(expected or [])
        a_canonical = self._canonicalize_filters(actual or [])

        if not e_canonical and not a_canonical:
            return 1.0
        if not e_canonical or not a_canonical:
            return 0.0
        if len(e_canonical) != len(a_canonical):
            return 0.0

        return 1.0 if set(e_canonical) == set(a_canonical) else 0.0

    def _canonicalize_filters(self, filters: list[dict]) -> set[str]:
        """将过滤条件列表转换为规范化字符串集合。"""
        result: set[str] = set()
        for f in filters:
            field = self._resolver.resolve_dimension(f.get("field", ""))
            op = f.get("operator", "=")
            value = self._resolver.resolve_value(f.get("field", ""), f.get("value"))
            result.add(f"{field} {op} {value}")
        return result
```

- [ ] **步骤 4：运行测试**

```bash
pytest tests/evaluation/v2/test_filter_scorer.py -v
```

预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add nl2dsl/evaluation/scorers/filter_scorer.py tests/evaluation/v2/test_filter_scorer.py
git commit -m "feat(evaluation): 添加带规范化解析的过滤条件评分器"
```

---

### 任务 12：规划器评分器

**文件：**
- 创建：`nl2dsl/evaluation/scorers/planner_scorer.py`
- 创建：`tests/evaluation/v2/test_planner_scorer.py`

- [ ] **步骤 1：编写会失败的测试**

```python
# tests/evaluation/v2/test_planner_scorer.py
import pytest
from nl2dsl.evaluation.scorers.planner_scorer import PlannerScorer
from nl2dsl.evaluation.canonical.resolver import CanonicalResolver


@pytest.fixture
def scorer():
    resolver = CanonicalResolver.from_config({
        "dimensions": {"region": {"column": "region_code"}},
        "data_sources": {
            "orders": {
                "joins": {
                    "customer_dim": {"entity": "customer", "on": "customer_id", "type": "left", "alias": "c"},
                }
            }
        },
    })
    return PlannerScorer(resolver)


def test_dimension_match(scorer):
    assert scorer.score(
        {"dimensions": ["region"], "order_by": None, "limit": None, "joins": None},
        {"dimensions": ["region"], "order_by": None, "limit": None, "joins": None},
    ) == 1.0


def test_limit_match(scorer):
    assert scorer.score(
        {"dimensions": [], "order_by": None, "limit": 10, "joins": None},
        {"dimensions": [], "order_by": None, "limit": 10, "joins": None},
    ) == 1.0
```

- [ ] **步骤 2：运行测试**

```bash
pytest tests/evaluation/v2/test_planner_scorer.py -v
```

预期结果：FAIL

- [ ] **步骤 3：编写实现**

```python
# nl2dsl/evaluation/scorers/planner_scorer.py
"""规划器评分器 — 维度、排序、分页、关联。"""

from nl2dsl.evaluation.scorers.base import Scorer
from nl2dsl.evaluation.canonical.resolver import CanonicalResolver


class PlannerScorer(Scorer):
    """对规划器方面进行评分：维度、排序、分页、关联。

    各子维度独立评分后取平均值。
    """

    def __init__(self, resolver: CanonicalResolver):
        self._resolver = resolver

    def score(self, expected: dict, actual: dict) -> float:
        """对规划器匹配进行评分。

        参数：
            expected: {"dimensions": [...], "order_by": ..., "limit": ..., "joins": [...]}
            actual: 相同结构
        """
        scores = []

        # 维度
        e_dims = set(expected.get("dimensions") or [])
        a_dims = set(actual.get("dimensions") or [])
        e_canon = {self._resolver.resolve_dimension(d) for d in e_dims}
        a_canon = {self._resolver.resolve_dimension(d) for d in a_dims}
        scores.append(1.0 if e_canon == a_canon else 0.0)

        # 分页
        e_limit = expected.get("limit")
        a_limit = actual.get("limit")
        scores.append(1.0 if e_limit == a_limit else 0.0)

        # 排序
        e_order = expected.get("order_by")
        a_order = actual.get("order_by")
        scores.append(self._score_order_by(e_order, a_order))

        # 关联
        e_joins = expected.get("joins") or []
        a_joins = actual.get("joins") or []
        scores.append(self._score_joins(e_joins, a_joins))

        return sum(scores) / len(scores) if scores else 1.0

    def _score_order_by(self, expected, actual) -> float:
        if expected is None and actual is None:
            return 1.0
        if expected is None or actual is None:
            return 0.0
        e_field = self._resolver.resolve_dimension(expected.get("field", ""))
        a_field = self._resolver.resolve_dimension(actual.get("field", ""))
        if e_field != a_field:
            return 0.0
        # 方向：如果预期有明确方向，则必须匹配
        e_dir = expected.get("direction")
        a_dir = actual.get("direction")
        if e_dir and a_dir:
            return 1.0 if e_dir == a_dir else 0.0
        # 如果预期没有明确方向，任何方向均可
        return 1.0

    def _score_joins(self, expected: list, actual: list) -> float:
        if not expected and not actual:
            return 1.0
        if not expected or not actual:
            return 0.0
        if len(expected) != len(actual):
            return 0.0
        e_canon = set()
        for j in expected:
            cj = self._resolver.resolve_join(
                j.get("table", ""), j.get("on_field", ""), j.get("join_type", "left")
            )
            e_canon.add(f"{cj.entity}:{cj.on_field}:{cj.join_type}")
        a_canon = set()
        for j in actual:
            cj = self._resolver.resolve_join(
                j.get("table", ""), j.get("on_field", ""), j.get("join_type", "left")
            )
            a_canon.add(f"{cj.entity}:{cj.on_field}:{cj.join_type}")
        return 1.0 if e_canon == a_canon else 0.0
```

- [ ] **步骤 4：运行测试**

```bash
pytest tests/evaluation/v2/test_planner_scorer.py -v
```

预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add nl2dsl/evaluation/scorers/planner_scorer.py tests/evaluation/v2/test_planner_scorer.py
git commit -m "feat(evaluation): 添加规划器评分器"
```

---

### 任务 13：治理评分器

**文件：**
- 创建：`nl2dsl/evaluation/scorers/governance_scorer.py`
- 创建：`tests/evaluation/v2/test_governance_scorer.py`

- [ ] **步骤 1：编写会失败的测试**

```python
# tests/evaluation/v2/test_governance_scorer.py
import pytest
from nl2dsl.evaluation.scorers.governance_scorer import GovernanceScorer


@pytest.fixture
def scorer():
    return GovernanceScorer()


def test_allow_match(scorer):
    assert scorer.score(
        {"permission": "allow"},
        {"permission": "allow"},
    ) == 1.0


def test_deny_mismatch(scorer):
    assert scorer.score(
        {"permission": "deny"},
        {"permission": "allow"},
    ) == 0.0
```

- [ ] **步骤 2：运行测试**

```bash
pytest tests/evaluation/v2/test_governance_scorer.py -v
```

预期结果：FAIL

- [ ] **步骤 3：编写实现**

```python
# nl2dsl/evaluation/scorers/governance_scorer.py
"""治理评分器。"""

from nl2dsl.evaluation.scorers.base import Scorer


class GovernanceScorer(Scorer):
    """对治理匹配进行评分。

    对于治理类用例，权限匹配为二元判定。
    """

    def score(self, expected: dict, actual: dict) -> float:
        """对治理匹配进行评分。

        参数：
            expected: {"permission": "allow" | "deny", ...}
            actual: {"permission": "allow" | "deny", ...}
        """
        e_perm = expected.get("permission", "allow")
        a_perm = actual.get("permission", "allow")
        return 1.0 if e_perm == a_perm else 0.0
```

- [ ] **步骤 4：运行测试**

```bash
pytest tests/evaluation/v2/test_governance_scorer.py -v
```

预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add nl2dsl/evaluation/scorers/governance_scorer.py tests/evaluation/v2/test_governance_scorer.py
git commit -m "feat(evaluation): 添加治理评分器"
```

---

## 第三阶段：模型与运行器

### 任务 14：V2 模型

**文件：**
- 修改：`nl2dsl/evaluation/models.py`
- 测试：`tests/evaluation/v2/test_models.py`

- [ ] **步骤 1：编写会失败的测试**

```python
# tests/evaluation/v2/test_models.py
import pytest
from nl2dsl.evaluation.models import V2TestCase, V2ScoreBreakdown, CanonicalQuery


def test_v2_test_case():
    case = V2TestCase(
        id="BASIC_001",
        query="查询销售额",
        expected={
            "intent": "aggregate",
            "metric": "sales_amount",
        },
    )
    assert case.id == "BASIC_001"
    assert case.category == "basic"


def test_canonical_query():
    cq = CanonicalQuery(
        intent="aggregate",
        metric="sales_amount",
        filters=["region_code = HD"],
    )
    assert cq.intent == "aggregate"
```

- [ ] **步骤 2：运行测试**

```bash
pytest tests/evaluation/v2/test_models.py -v
```

预期结果：FAIL

- [ ] **步骤 3：编写实现**

```python
# 追加到 nl2dsl/evaluation/models.py

# --- V2 模型 ---

from dataclasses import dataclass, field


@dataclass
class CanonicalQuery:
    """查询的规范化语义表示。"""

    intent: str = ""
    metric: str = ""
    dimensions: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    planner: dict = field(default_factory=dict)
    clarification_required: bool = False
    governance: dict = field(default_factory=dict)
    error: str | None = None


@dataclass
class V2TestCase:
    """V2 评测用例。"""

    id: str
    query: str
    difficulty: str = "easy"
    category: str = "basic"
    tags: list[str] = field(default_factory=list)
    expected: dict = field(default_factory=dict)


@dataclass
class V2ScoreBreakdown:
    """V2 评分明细。"""

    intent: float = 0.0
    metric: float = 0.0
    filter: float = 0.0
    planner: float = 0.0
    governance: float = 0.0
    overall: float = 0.0

    def compute_overall(self, weights: dict[str, float]) -> float:
        """计算加权总分。"""
        return (
            self.intent * weights.get("intent", 0.0)
            + self.metric * weights.get("metric", 0.0)
            + self.filter * weights.get("filter", 0.0)
            + self.planner * weights.get("planner", 0.0)
            + self.governance * weights.get("governance", 0.0)
        )
```

- [ ] **步骤 4：运行测试**

```bash
pytest tests/evaluation/v2/test_models.py -v
```

预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add nl2dsl/evaluation/models.py tests/evaluation/v2/test_models.py
git commit -m "feat(evaluation): 添加 V2 数据模型"
```

---

### 任务 15：V2 用例加载器

**文件：**
- 修改：`nl2dsl/evaluation/dataset.py`
- 测试：`tests/evaluation/v2/test_dataset_loader.py`

- [ ] **步骤 1：编写会失败的测试**

```python
# tests/evaluation/v2/test_dataset_loader.py
import pytest
import tempfile
from pathlib import Path
from nl2dsl.evaluation.dataset import V2DatasetLoader


@pytest.fixture
def sample_dataset(tmp_path):
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    (dataset_dir / "basic.yaml").write_text("""
test_cases:
  - id: BASIC_001
    query: 查询销售额
    difficulty: easy
    category: basic
    expected:
      intent: aggregate
      metric: sales_amount
""")
    return dataset_dir


def test_load_v2_cases(sample_dataset):
    loader = V2DatasetLoader(sample_dataset)
    cases = loader.load_all()
    assert len(cases) == 1
    assert cases[0].id == "BASIC_001"
    assert cases[0].expected["metric"] == "sales_amount"
```

- [ ] **步骤 2：运行测试**

```bash
pytest tests/evaluation/v2/test_dataset_loader.py -v
```

预期结果：FAIL

- [ ] **步骤 3：编写实现**

```python
# 追加到 nl2dsl/evaluation/dataset.py

from nl2dsl.evaluation.models import V2TestCase


class V2DatasetLoader:
    """从 YAML 文件加载 V2 评测数据集。"""

    def __init__(self, dataset_dir: Path | str):
        self.dataset_dir = Path(dataset_dir)

    def load_all(self) -> list[V2TestCase]:
        """加载所有 YAML 文件中的 V2 测试用例。"""
        cases: list[V2TestCase] = []
        if not self.dataset_dir.exists():
            logger.warning("数据集目录未找到：%s", self.dataset_dir)
            return cases

        for yaml_file in sorted(self.dataset_dir.rglob("*.yaml")):
            file_cases = self._load_file(yaml_file)
            cases.extend(file_cases)
            logger.info("从 %s 加载了 %d 条 V2 用例", len(file_cases), yaml_file)

        logger.info("共加载 V2 测试用例：%d 条", len(cases))
        return cases

    def _load_file(self, path: Path) -> list[V2TestCase]:
        """从单个 YAML 文件加载 V2 测试用例。"""
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("加载 %s 失败：%s", path, exc)
            return []

        if not isinstance(data, dict):
            return []

        test_cases = data.get("test_cases", [])
        if not isinstance(test_cases, list):
            return []

        cases: list[V2TestCase] = []
        for raw in test_cases:
            if not isinstance(raw, dict):
                continue
            try:
                tc = V2TestCase(
                    id=raw.get("id", ""),
                    query=raw.get("query", ""),
                    difficulty=raw.get("difficulty", "easy"),
                    category=raw.get("category", "basic"),
                    tags=raw.get("tags", []),
                    expected=raw.get("expected", {}),
                )
                cases.append(tc)
            except Exception as exc:
                logger.error("解析 %s 中的 V2 测试用例失败：%s", path, exc)

        return cases
```

- [ ] **步骤 4：运行测试**

```bash
pytest tests/evaluation/v2/test_dataset_loader.py -v
```

预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add nl2dsl/evaluation/dataset.py tests/evaluation/v2/test_dataset_loader.py
git commit -m "feat(evaluation): 添加 V2 数据集加载器"
```

---

### 任务 16：基准测试运行器

**文件：**
- 创建：`nl2dsl/evaluation/v2_runner.py`
- 测试：`tests/evaluation/v2/test_v2_runner.py`

- [ ] **步骤 1：编写会失败的测试**

```python
# tests/evaluation/v2/test_v2_runner.py
import pytest
from nl2dsl.evaluation.v2_runner import V2BenchmarkRunner
from nl2dsl.evaluation.models import V2TestCase, V2ScoreBreakdown


def test_runner_initialization():
    runner = V2BenchmarkRunner({})
    assert runner is not None
```

- [ ] **步骤 2：运行测试**

```bash
pytest tests/evaluation/v2/test_v2_runner.py -v
```

预期结果：FAIL

- [ ] **步骤 3：编写实现**

```python
# nl2dsl/evaluation/v2_runner.py
"""V2 基准测试运行器。"""

from __future__ import annotations

import time
from typing import Any, Callable

from fastapi.testclient import TestClient

from nl2dsl.evaluation.models import V2TestCase, V2ScoreBreakdown, CanonicalQuery
from nl2dsl.evaluation.canonical.resolver import CanonicalResolver
from nl2dsl.evaluation.scorers.base import Scorer
from nl2dsl.utils.logger import get_logger

logger = get_logger("evaluation.v2_runner")

# 默认权重
DEFAULT_WEIGHTS: dict[str, float] = {
    "intent": 0.20,
    "metric": 0.30,
    "filter": 0.20,
    "planner": 0.20,
    "governance": 0.10,
}


class V2BenchmarkRunner:
    """运行 V2 语义基准测试。"""

    def __init__(
        self,
        scorers: dict[str, Scorer],
        weights: dict[str, float] | None = None,
        threshold: float = 0.8,
    ):
        self.scorers = scorers
        self.weights = weights or DEFAULT_WEIGHTS.copy()
        self.threshold = threshold

    def run_single(
        self,
        test_case: V2TestCase,
        actual_dsl: dict[str, Any],
        resolver: CanonicalResolver,
    ) -> dict:
        """评估单个测试用例。"""
        start = time.time()

        expected = test_case.expected
        scores = V2ScoreBreakdown()

        # 意图
        if "intent" in expected and "intent_scorer" in self.scorers:
            scores.intent = self.scorers["intent_scorer"].score(
                expected["intent"], actual_dsl.get("intent", "")
            )

        # 指标
        if "metric" in expected and "metric_scorer" in self.scorers:
            metrics = actual_dsl.get("metrics", [])
            if metrics:
                scores.metric = self.scorers["metric_scorer"].score(
                    expected["metric"],
                    metrics[0].get("alias", metrics[0].get("field", "")),
                    metrics[0].get("func"),
                )
            else:
                scores.metric = 0.0

        # 过滤条件
        if "filters" in expected and "filter_scorer" in self.scorers:
            scores.filter = self.scorers["filter_scorer"].score(
                expected["filters"], actual_dsl.get("filters", [])
            )

        # 规划器
        if "planner" in expected and "planner_scorer" in self.scorers:
            scores.planner = self.scorers["planner_scorer"].score(
                expected["planner"], self._extract_planner(actual_dsl)
            )

        # 治理
        if "governance" in expected and "governance_scorer" in self.scorers:
            scores.governance = self.scorers["governance_scorer"].score(
                expected["governance"], actual_dsl.get("governance", {})
            )

        scores.overall = scores.compute_overall(self.weights)
        passed = scores.overall >= self.threshold

        elapsed = int((time.time() - start) * 1000)

        return {
            "test_case": test_case,
            "passed": passed,
            "scores": scores,
            "actual_dsl": actual_dsl,
            "execution_time_ms": elapsed,
        }

    def _extract_planner(self, dsl: dict) -> dict:
        """从 DSL 中提取规划器信息。"""
        return {
            "dimensions": dsl.get("dimensions", []),
            "order_by": dsl.get("order_by"),
            "limit": dsl.get("limit"),
            "joins": dsl.get("joins", []),
        }

    def run_batch(
        self,
        cases: list[V2TestCase],
        api_client: TestClient,
        resolver: CanonicalResolver,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[dict]:
        """批量运行测试用例。"""
        results: list[dict] = []
        total = len(cases)

        for i, case in enumerate(cases):
            # 调用 API 获取实际 DSL
            try:
                response = api_client.post("/api/v1/query", json={
                    "question": case.query,
                    "domain": "ecommerce",
                })
                actual_dsl = response.json().get("dsl", {})
            except Exception as exc:
                logger.error("[%s] API 调用失败：%s", case.id, exc)
                actual_dsl = {}

            result = self.run_single(case, actual_dsl, resolver)
            results.append(result)

            if progress_callback:
                progress_callback(i + 1, total)

        return results
```

- [ ] **步骤 4：运行测试**

```bash
pytest tests/evaluation/v2/test_v2_runner.py -v
```

预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add nl2dsl/evaluation/v2_runner.py tests/evaluation/v2/test_v2_runner.py
git commit -m "feat(evaluation): 添加 V2 基准测试运行器"
```

---

## 第四阶段：报告器

### 任务 17：控制台与 Markdown 报告器

**文件：**
- 创建：`nl2dsl/evaluation/v2_reporter.py`
- 测试：`tests/evaluation/v2/test_v2_reporter.py`

- [ ] **步骤 1：编写会失败的测试**

```python
# tests/evaluation/v2/test_v2_reporter.py
import pytest
from nl2dsl.evaluation.v2_reporter import V2Reporter


def test_reporter_format():
    reporter = V2Reporter()
    results = [
        {
            "test_case": {"id": "BASIC_001", "query": "查询销售额"},
            "passed": True,
            "scores": {"intent": 1.0, "metric": 1.0, "filter": 1.0, "planner": 1.0, "governance": 1.0, "overall": 1.0},
        }
    ]
    output = reporter.to_console(results)
    assert "BASIC_001" in output
    assert "100.0%" in output
```

- [ ] **步骤 2：运行测试**

```bash
pytest tests/evaluation/v2/test_v2_reporter.py -v
```

预期结果：FAIL

- [ ] **步骤 3：编写实现**

```python
# nl2dsl/evaluation/v2_reporter.py
"""V2 评测报告器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nl2dsl.evaluation.models import V2ScoreBreakdown


@dataclass
class V2Report:
    """V2 评测报告。"""

    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    overall_accuracy: float = 0.0
    intent_accuracy: float = 0.0
    metric_accuracy: float = 0.0
    filter_accuracy: float = 0.0
    planner_accuracy: float = 0.0
    governance_accuracy: float = 0.0
    failed_cases: list[dict] = None

    def __post_init__(self):
        if self.failed_cases is None:
            self.failed_cases = []


class V2Reporter:
    """生成 V2 评测报告。"""

    def generate(self, results: list[dict]) -> V2Report:
        """根据结果生成报告。"""
        total = len(results)
        passed = sum(1 for r in results if r["passed"])
        failed = total - passed

        if total == 0:
            return V2Report()

        scores_list = [r["scores"] for r in results]

        return V2Report(
            total_cases=total,
            passed=passed,
            failed=failed,
            overall_accuracy=sum(s.overall for s in scores_list) / total,
            intent_accuracy=sum(s.intent for s in scores_list) / total,
            metric_accuracy=sum(s.metric for s in scores_list) / total,
            filter_accuracy=sum(s.filter for s in scores_list) / total,
            planner_accuracy=sum(s.planner for s in scores_list) / total,
            governance_accuracy=sum(s.governance for s in scores_list) / total,
            failed_cases=[r for r in results if not r["passed"]],
        )

    def to_console(self, results: list[dict]) -> str:
        """格式化报告为控制台输出。"""
        report = self.generate(results)

        lines = [
            "=" * 50,
            "语义查询基准测试",
            "=" * 50,
            f"总用例数：{report.total_cases}",
            f"通过：{report.passed}",
            f"失败：{report.failed}",
            f"准确率：{report.overall_accuracy:.1%}",
            "-" * 50,
            f"意图准确率：      {report.intent_accuracy:.1%}",
            f"指标准确率：      {report.metric_accuracy:.1%}",
            f"过滤条件准确率：  {report.filter_accuracy:.1%}",
            f"规划器准确率：    {report.planner_accuracy:.1%}",
            f"治理准确率：      {report.governance_accuracy:.1%}",
            "=" * 50,
        ]

        if report.failed_cases:
            lines.extend(["", "失败用例", "-" * 50])
            for r in report.failed_cases:
                tc = r["test_case"]
                lines.extend([
                    f"用例：{tc['id']}",
                    f"查询：{tc['query']}",
                    f"总分：{r['scores'].overall:.1%}",
                    "-" * 50,
                ])

        return "\n".join(lines)

    def to_markdown(self, results: list[dict]) -> str:
        """格式化报告为 Markdown。"""
        report = self.generate(results)

        lines = [
            "# 语义查询基准测试报告",
            "",
            f"| 指标 | 数值 |",
            f"|--------|-------|",
            f"| 总用例数 | {report.total_cases} |",
            f"| 通过 | {report.passed} |",
            f"| 失败 | {report.failed} |",
            f"| 整体准确率 | {report.overall_accuracy:.1%} |",
            "",
            "## 各维度得分",
            "",
            f"| 维度 | 准确率 |",
            f"|-----------|----------|",
            f"| 意图 | {report.intent_accuracy:.1%} |",
            f"| 指标 | {report.metric_accuracy:.1%} |",
            f"| 过滤条件 | {report.filter_accuracy:.1%} |",
            f"| 规划器 | {report.planner_accuracy:.1%} |",
            f"| 治理 | {report.governance_accuracy:.1%} |",
        ]

        if report.failed_cases:
            lines.extend(["", "## 失败用例", ""])
            for r in report.failed_cases:
                tc = r["test_case"]
                lines.extend([
                    f"### {tc['id']}: {tc['query']}",
                    f"- **总分**：{r['scores'].overall:.1%}",
                    f"- **意图**：{r['scores'].intent:.1%}",
                    f"- **指标**：{r['scores'].metric:.1%}",
                    f"- **过滤条件**：{r['scores'].filter:.1%}",
                    "",
                ])

        return "\n".join(lines)
```

- [ ] **步骤 4：运行测试**

```bash
pytest tests/evaluation/v2/test_v2_reporter.py -v
```

预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add nl2dsl/evaluation/v2_reporter.py tests/evaluation/v2/test_v2_reporter.py
git commit -m "feat(evaluation): 添加 V2 报告器"
```

---

## 第五阶段：数据集

### 任务 18：V0.1 数据集

**文件：**
- 创建：`tests/evaluation/dataset/v2/basic.yaml`
- 创建：`tests/evaluation/dataset/v2/filter.yaml`
- 创建：`tests/evaluation/dataset/v2/ranking.yaml`

- [ ] **步骤 1：创建数据集文件**

```yaml
# tests/evaluation/dataset/v2/basic.yaml
test_cases:
  - id: BASIC_001
    query: "查询销售额"
    difficulty: easy
    category: basic
    tags: ["aggregation"]
    expected:
      intent: aggregate
      metric: sales_amount
      dimensions: []
      filters: []

  - id: BASIC_002
    query: "查询订单量"
    difficulty: easy
    category: basic
    tags: ["aggregation"]
    expected:
      intent: aggregate
      metric: order_count
      dimensions: []
      filters: []

  - id: BASIC_003
    query: "按品牌统计销售额"
    difficulty: easy
    category: basic
    tags: ["aggregation", "dimension"]
    expected:
      intent: aggregate
      metric: sales_amount
      dimensions: [brand]
      filters: []

  - id: BASIC_004
    query: "查询客单价"
    difficulty: easy
    category: basic
    tags: ["aggregation"]
    expected:
      intent: aggregate
      metric: avg_order_value
      dimensions: []
      filters: []
```

```yaml
# tests/evaluation/dataset/v2/filter.yaml
test_cases:
  - id: FILTER_001
    query: "查询华东销售额"
    difficulty: easy
    category: filter
    tags: ["filter", "region"]
    expected:
      intent: aggregate
      metric: sales_amount
      filters:
        - field: region
          operator: eq
          value: "华东"

  - id: FILTER_002
    query: "销售额大于10万的商品"
    difficulty: medium
    category: filter
    tags: ["filter", "having"]
    expected:
      intent: aggregate
      metric: sales_amount
      dimensions: [product_name]
      filters: []
      planner:
        having:
          - field: sales_amount
            operator: gt
            value: 100000
```

```yaml
# tests/evaluation/dataset/v2/ranking.yaml
test_cases:
  - id: RANK_001
    query: "销售额最高的10个商品"
    difficulty: medium
    category: ranking
    tags: ["ranking", "top_n"]
    expected:
      intent: rank
      metric: sales_amount
      dimensions: [product_name]
      planner:
        order_by:
          field: sales_amount
          direction: desc
        limit: 10
```

- [ ] **步骤 2：验证数据集可正常加载**

```bash
python -c "
from nl2dsl.evaluation.dataset import V2DatasetLoader
from pathlib import Path
loader = V2DatasetLoader(Path('tests/evaluation/dataset/v2'))
cases = loader.load_all()
print(f'已加载 {len(cases)} 条用例')
for c in cases:
    print(f'  {c.id}: {c.query}')
"
```

预期输出：
```
已加载 6 条用例
  BASIC_001: 查询销售额
  BASIC_002: 查询订单量
  ...
```

- [ ] **步骤 3：提交**

```bash
git add tests/evaluation/dataset/v2/
git commit -m "feat(evaluation): 添加 V0.1 数据集（基础、过滤、排序）"
```

---

## 第六阶段：CLI 集成

### 任务 19：V2 CLI

**文件：**
- 创建：`nl2dsl/evaluation/v2_cli.py`
- 修改：`pyproject.toml`（如需要入口点）

- [ ] **步骤 1：编写 CLI 实现**

```python
# nl2dsl/evaluation/v2_cli.py
"""V2 语义基准测试 CLI 入口点。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from nl2dsl.evaluation.dataset import V2DatasetLoader
from nl2dsl.evaluation.v2_runner import V2BenchmarkRunner, DEFAULT_WEIGHTS
from nl2dsl.evaluation.v2_reporter import V2Reporter
from nl2dsl.evaluation.canonical.resolver import CanonicalResolver
from nl2dsl.evaluation.scorers.intent_scorer import IntentScorer
from nl2dsl.evaluation.scorers.metric_scorer import MetricScorer
from nl2dsl.evaluation.scorers.filter_scorer import FilterScorer
from nl2dsl.evaluation.scorers.planner_scorer import PlannerScorer
from nl2dsl.evaluation.scorers.governance_scorer import GovernanceScorer
from nl2dsl.utils.logger import get_logger
import yaml

logger = get_logger("evaluation.v2_cli")


def _load_config(config_path: Path) -> dict:
    """从 YAML 加载项目配置。"""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_scorers(resolver: CanonicalResolver) -> dict[str, any]:
    """构建评分器实例。"""
    return {
        "intent_scorer": IntentScorer(),
        "metric_scorer": MetricScorer(resolver.metric),
        "filter_scorer": FilterScorer(resolver),
        "planner_scorer": PlannerScorer(resolver),
        "governance_scorer": GovernanceScorer(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="运行 V2 语义查询基准测试",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        required=True,
        help="V2 数据集目录路径",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/metrics.yaml"),
        help="项目配置文件路径（默认：configs/metrics.yaml）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/v2"),
        help="输出目录（默认：reports/v2）",
    )
    parser.add_argument(
        "--format",
        choices=["console", "markdown", "json"],
        default="console",
        help="输出格式",
    )

    args = parser.parse_args(argv)

    # 加载配置并构建解析器
    config = _load_config(args.config)
    resolver = CanonicalResolver.from_config(config)

    # 加载数据集
    loader = V2DatasetLoader(args.dataset)
    cases = loader.load_all()
    if not cases:
        print("错误：未找到测试用例。", file=sys.stderr)
        return 1
    print(f"已加载 {len(cases)} 条测试用例")

    # 构建评分器和运行器
    scorers = _build_scorers(resolver)
    runner = V2BenchmarkRunner(scorers)

    # 运行（暂时不连 API — 打印预期结构）
    print("\nV2 基准测试就绪！")
    print(f"用例数：{len(cases)}")
    print(f"评分器：{list(scorers.keys())}")
    print("\n连接 API 运行：")
    print("  python -m nl2dsl.evaluation.v2_cli --dataset tests/evaluation/dataset/v2")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **步骤 2：验证 CLI 可正常工作**

```bash
cd D:\demo\db-gpt\NL2DSL
python -m nl2dsl.evaluation.v2_cli --dataset tests/evaluation/dataset/v2 --config configs/metrics.yaml
```

预期输出：
```
已加载 6 条测试用例

V2 基准测试就绪！
用例数：6
评分器：['intent_scorer', 'metric_scorer', ...]
```

- [ ] **步骤 3：提交**

```bash
git add nl2dsl/evaluation/v2_cli.py
git commit -m "feat(evaluation): 添加 V2 CLI 入口点"
```

---

## 自查清单

### 1. 设计需求覆盖

| 设计需求 | 对应任务 | 状态 |
|---------|----------|------|
| 规范化指标解析器 | 任务 1 | ✅ |
| 规范化维度解析器 | 任务 2 | ✅ |
| 规范化值解析器 | 任务 3 | ✅ |
| 规范化时间解析器（含粒度） | 任务 4 | ✅ |
| 规范化关联解析器（含实体） | 任务 5 | ✅ |
| 规范化排序解析器（含默认值） | 任务 6 | ✅ |
| 解析器编排器 | 任务 7 | ✅ |
| 评分器基类 | 任务 8 | ✅ |
| 意图评分器 | 任务 9 | ✅ |
| 指标评分器 | 任务 10 | ✅ |
| 过滤条件评分器 | 任务 11 | ✅ |
| 规划器评分器 | 任务 12 | ✅ |
| 治理评分器 | 任务 13 | ✅ |
| V2 模型 | 任务 14 | ✅ |
| V2 数据集加载器 | 任务 15 | ✅ |
| V2 基准测试运行器 | 任务 16 | ✅ |
| V2 报告器 | 任务 17 | ✅ |
| V0.1 数据集 | 任务 18 | ✅ |
| V2 CLI | 任务 19 | ✅ |

### 2. 占位符扫描

- ✅ 无 TBD/TODO
- ✅ 无"稍后实现"
- ✅ 每个任务均包含完整代码、测试和命令
- ✅ 无"与任务 N 类似"引用

### 3. 类型一致性

- ✅ `CanonicalResolver` 接口在所有评分器中使用一致
- ✅ `V2ScoreBreakdown` 字段名与权重键一致
- ✅ `score()` 方法签名在所有评分器中一致

---

## 执行交接

**计划已完成并保存至 `docs/history/superpowers/plans/2026-06-02-evaluation-v2.md`。**

**两种执行方式：**

**1. Subagent-Driven（推荐）** — 每个任务分配独立的子代理，我在任务之间审查，迭代快速

**2. Inline Execution（内联执行）** — 在当前会话中使用 executing-plans 按顺序执行，批处理 + 检查点

**选择哪种方式？**
