# 统计信息纳入治理层 + A/C 类 SQL 调优 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将表/列统计信息(定性等级)纳入治理层 `metrics.yaml`,驱动 SQL 语句级调优:like SARGable 通配符分流、filter 值类型对齐、join 按 size 重排。

**Architecture:** 治理层注册 `size`/`selectivity`/`indexed` 三字段 → `SemanticConfig` 暴露 getter → optimizer 新增 F006 规则(like on 枚举维度 → `in`,DSL 层修正可观测)→ builder 消费统计信息做 SQL 编译决策(like 通配符方向、类型对齐、join 重排)。B 类运行时 EXPLAIN 不在本计划。

**Tech Stack:** Python 3.11+, SQLAlchemy Core, Pydantic, PyYAML, pytest

## Global Constraints

- 三个新字段(`size`/`selectivity`/`indexed`)**全部可选**,缺省时 builder/optimizer 退回当前行为
- 命名固定:`size`(data_source,large/medium/small)、`selectivity`(dimension,high/medium/low)、`indexed`(dimension,bool),不用 `cardinality`
- F006 把 like on 枚举维度改成 `in`(单值包装为 `[value]`),不是 `=`
- join 重排只按 `size`,同等级保持依赖顺序;有跨依赖(`on_field` 含 `.`)的 join 链不重排
- 类型对齐:无损场景(数值列+数字字符串)显式 cast;有损场景(字符串列+数字)显式转 str + 告警;不匹配告警放行
- 不引入 sql_engine → optimizer 循环依赖(optimizer.context 不依赖 sql_engine,单向可)
- 遵循 CLAUDE.md:不发明指标/维度;新增功能必须加评测用例

---

## File Structure

| 文件 | 职责 | 改动 |
|------|------|------|
| `configs/metrics.yaml` | 电商域语义配置 | 修改:data_sources 加 `size`,dimensions 加 `selectivity`/`indexed` |
| `configs/bank_metrics.yaml` | 银行域语义配置 | 修改:同步补字段(可选) |
| `nl2dsl/optimizer/context.py` | SemanticConfig 类型化 wrapper | 修改:加 `get_size`/`get_selectivity`/`is_indexed` |
| `nl2dsl/optimizer/rules/filter.py` | Filter 规则 F001-F005 | 修改:加 F006 |
| `nl2dsl/sql_engine/builder.py` | SQL 构建 | 修改:构造函数加 `semantic_config`;`_build_leaf_condition` like 分流 + 类型对齐;`_determine_required_joins` 加 size 重排 |
| `nl2dsl/engine.py` | 引擎装配 | 修改:SQLBuilder 实例化处传 `semantic_config` |
| `nl2dsl/api_factory.py` | API 装配 | 修改:两处 SQLBuilder 实例化传 `semantic_config` |
| `tests/unit/test_semantic_config.py` | SemanticConfig 测试 | 修改:加 getter 测试 |
| `tests/unit/optimizer/rules/test_filter.py` | Filter 规则测试 | 修改:加 F006 测试 |
| `tests/unit/test_sql_builder.py` | builder 测试 | 修改:加 like 分流/类型对齐/join 重排测试 |
| `tests/evaluation/dataset/` | 评测用例 | 修改:加 like/join/类型边界用例 |

---

## Task 1: 配置 schema + SemanticConfig getter

**Files:**
- Modify: `configs/metrics.yaml`
- Modify: `nl2dsl/optimizer/context.py`
- Test: `tests/unit/test_semantic_config.py`

**Interfaces:**
- Produces: `SemanticConfig.get_size(data_source) -> str | None`、`get_selectivity(dimension) -> str | None`、`is_indexed(dimension) -> bool`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_semantic_config.py` 末尾追加:

```python
def test_statistics_getters():
    """size/selectivity/indexed 字段可被 getter 读取,缺省返回安全值。"""
    from nl2dsl.optimizer.context import SemanticConfig

    config = SemanticConfig(
        data_sources={
            "orders": {"table": "order_fact", "size": "large"},
            "suppliers": {"table": "supplier_dim", "size": "small"},
            "no_size": {"table": "t"},
        },
        dimensions={
            "order_date": {"column": "order_date", "type": "date", "selectivity": "high", "indexed": True},
            "region": {"column": "region", "type": "string", "selectivity": "low", "indexed": True},
            "product_name": {"column": "product_name", "type": "string", "selectivity": "high", "indexed": False},
            "no_stats": {"column": "x", "type": "string"},
        },
    )

    assert config.get_size("orders") == "large"
    assert config.get_size("suppliers") == "small"
    assert config.get_size("no_size") is None
    assert config.get_size("missing") is None

    assert config.get_selectivity("order_date") == "high"
    assert config.get_selectivity("region") == "low"
    assert config.get_selectivity("no_stats") is None

    assert config.is_indexed("order_date") is True
    assert config.is_indexed("product_name") is False
    assert config.is_indexed("no_stats") is False
    assert config.is_indexed("missing") is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_semantic_config.py::test_statistics_getters -v`
Expected: FAIL with `AttributeError: 'SemanticConfig' object has no attribute 'get_size'`

- [ ] **Step 3: 加 SemanticConfig getter**

在 `nl2dsl/optimizer/context.py` 的 `SemanticConfig` 类中,`find_data_source_for_dimension` 方法之后(类末尾)追加三个方法:

```python
    def get_size(self, data_source: str) -> str | None:
        """返回 data_source 的表大小等级:large/medium/small,缺省 None。"""
        ds = self.data_sources.get(data_source, {})
        return ds.get("size")

    def get_selectivity(self, dimension: str) -> str | None:
        """返回 dimension 的过滤选择性等级:high/medium/low,缺省 None。"""
        d = self.dimensions.get(dimension, {})
        return d.get("selectivity")

    def is_indexed(self, dimension: str) -> bool:
        """返回 dimension 是否建索引,缺省 False。"""
        d = self.dimensions.get(dimension, {})
        return bool(d.get("indexed", False))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/test_semantic_config.py::test_statistics_getters -v`
Expected: PASS

- [ ] **Step 5: 给 metrics.yaml 补统计字段**

在 `configs/metrics.yaml` 的 `data_sources` 段,每个 source 加 `size`:

```yaml
data_sources:
  orders:
    table: order_fact
    size: large
    metrics: [sales_amount, gmv, order_count, avg_order_value, total_discount]
    dimensions: [product_name, region, order_date, brand, category, channel, customer_type]
    joins:
      product_dim:
        on: product_id
        type: inner
        alias: p
      customer_dim:
        on: customer_id
        type: left
        alias: c
      supplier_dim:
        on: p.supplier_id
        type: left
        alias: s
  products:
    table: product_dim
    size: medium
    metrics: [max_price, avg_price]
    dimensions: [product_name, brand, category, price]
  customers:
    table: customer_dim
    size: medium
    metrics: [customer_count]
    dimensions: [customer_name, customer_type, region, city_level]
  suppliers:
    table: supplier_dim
    size: small
    metrics: []
    dimensions: [supplier_name]
```

在 `dimensions` 段,给每个维度加 `selectivity` 和 `indexed`:

```yaml
dimensions:
  product_name:
    column: product_name
    type: string
    selectivity: high
    indexed: false
    description: "产品名称"
  region:
    column: region
    type: string
    selectivity: low
    indexed: true
    description: "地区"
    value_map:
      华东: HD
      华南: HN
      华北: HB
      华西: HX
  order_date:
    column: order_date
    type: date
    selectivity: high
    indexed: true
    description: "订单日期"
  brand:
    column: brand
    type: string
    selectivity: low
    indexed: false
    description: "品牌"
  category:
    column: category
    type: string
    selectivity: low
    indexed: false
    description: "品类"
    value_map:
      手机: phone
      电脑: computer
      服饰: apparel
      食品: food
  channel:
    column: channel
    type: string
    selectivity: low
    indexed: false
    description: "销售渠道"
    value_map:
      线上: online
      线下: offline
  customer_type:
    column: customer_type
    type: string
    selectivity: low
    indexed: false
    description: "客户类型"
    value_map:
      VIP: vip
      新客: new
      老客: old
  customer_name:
    column: customer_name
    type: string
    selectivity: high
    indexed: false
    description: "客户名称"
  city_level:
    column: city_level
    type: string
    selectivity: low
    indexed: false
    description: "城市等级"
  supplier_name:
    column: supplier_name
    type: string
    selectivity: high
    indexed: false
    description: "供应商名称"
  price:
    column: price
    type: float
    selectivity: high
    indexed: false
    description: "产品单价"
```

- [ ] **Step 6: 跑全部 semantic_config 测试确认无回归**

Run: `pytest tests/unit/test_semantic_config.py -v`
Expected: PASS(所有用例)

- [ ] **Step 7: Commit**

```bash
git add configs/metrics.yaml nl2dsl/optimizer/context.py tests/unit/test_semantic_config.py
git commit -m "feat(semantic): 注册统计信息字段 size/selectivity/indexed 到治理层"
```

---

## Task 2: F006 LikeOnEnumDimension 规则

**Files:**
- Modify: `nl2dsl/optimizer/rules/filter.py`
- Test: `tests/unit/optimizer/rules/test_filter.py`

**Interfaces:**
- Consumes: `SemanticConfig.get_value_map(dimension)`(Task 1 已存在,非新增)
- Produces: `F006_LikeOnEnumDimension` 规则类,`error_code="F006"`,把 `like` on 枚举维度改成 `in`(value 包装为 list)

- [ ] **Step 1: 写失败测试**

在 `tests/unit/optimizer/rules/test_filter.py` 末尾追加:

```python
def test_f006_like_on_enum_dimension_changes_to_in():
    """like 作用在有 value_map 的枚举维度 → 改 in,value 包装为 list。"""
    from nl2dsl.optimizer.context import SemanticConfig, RuleContext
    from nl2dsl.optimizer.engine import RuleEngine

    config = SemanticConfig(
        dimensions={
            "region": {"column": "region", "type": "string", "value_map": {"华东": "HD"}},
            "product_name": {"column": "product_name", "type": "string"},  # 无 value_map
        }
    )
    context = RuleContext(semantic_config=config)
    dsl = {
        "filters": [
            {"field": "region", "operator": "like", "value": "华东"},
            {"field": "product_name", "operator": "like", "value": "手机"},
        ]
    }
    optimized, report = RuleEngine(context).run(dsl)

    # region 的 like 被改成 in,value 包装为 list
    assert optimized["filters"][0]["operator"] == "in"
    assert optimized["filters"][0]["value"] == ["华东"]
    # product_name 无 value_map,不动
    assert optimized["filters"][1]["operator"] == "like"
    assert optimized["filters"][1]["value"] == "手机"
    # report 记录 F006 fix
    f006 = [f for f in report.fixes_applied if f["error_code"] == "F006"]
    assert len(f006) == 1


def test_f006_like_with_list_value_stays_list():
    """like 的 value 已是 list 时,in 保持 list 不双层包装。"""
    from nl2dsl.optimizer.context import SemanticConfig, RuleContext
    from nl2dsl.optimizer.engine import RuleEngine

    config = SemanticConfig(
        dimensions={"region": {"column": "region", "type": "string", "value_map": {"华东": "HD"}}}
    )
    context = RuleContext(semantic_config=config)
    dsl = {"filters": [{"field": "region", "operator": "like", "value": ["华东", "华南"]}]}
    optimized, _ = RuleEngine(context).run(dsl)
    assert optimized["filters"][0]["operator"] == "in"
    assert optimized["filters"][0]["value"] == ["华东", "华南"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/optimizer/rules/test_filter.py::test_f006_like_on_enum_dimension_changes_to_in -v`
Expected: FAIL(F006 规则未注册,like 未被改)

- [ ] **Step 3: 实现 F006 规则**

在 `nl2dsl/optimizer/rules/filter.py` 末尾(F005 之后)追加:

```python
@RuleRegistry.register
class F006_LikeOnEnumDimension(BaseRule):
    """like on a dimension with value_map should be 'in' (exact match).

    Enum dimensions (those with a value_map) should use exact match, not
    fuzzy LIKE. Replaces 'like' with 'in' and wraps scalar values in a list.
    """

    metadata = RuleMetadata(
        error_code="F006",
        category="Filter",
        description="like on enum dimension — replace with 'in' for exact match",
        priority=3,
        severity="Fix",
        confidence="high",
        auto_fixable=True,
    )

    def check(self, dsl: dict, context) -> RuleResult:
        filters = dsl.get("filters") or []
        if not filters:
            return RuleResult.no_issue("F006", "Filter")

        for i, f in enumerate(filters):
            if not isinstance(f, dict):
                continue
            if f.get("operator") != "like":
                continue
            field = f.get("field", "")
            value = f.get("value")
            if value is None:
                continue
            # Only trigger on dimensions with a value_map (enum)
            value_map = context.semantic_config.get_value_map(field)
            if not value_map:
                continue

            new_value = value if isinstance(value, list) else [value]
            return RuleResult.from_metadata(
                self.metadata,
                description=f"like on enum dimension '{field}' — replaced with 'in' for exact match",
                before={"operator": "like", "value": value},
                after={"operator": "in", "value": new_value},
                location=f"filters[{i}]",
            )
        return RuleResult.no_issue("F006", "Filter")

    def fix(self, dsl: dict, result: RuleResult) -> dict:
        """Override: 同时改 operator 和 value,保留 field。"""
        import copy
        dsl = copy.deepcopy(dsl)
        parts = result.location.replace("[", ".").replace("]", "").split(".")
        # parts == ["filters", "<i>"]
        if len(parts) < 2 or not parts[1].isdigit():
            return dsl
        idx = int(parts[1])
        filters = dsl.get("filters") or []
        if idx >= len(filters) or not isinstance(filters[idx], dict):
            return dsl
        after = result.after or {}
        filters[idx]["operator"] = after.get("operator", "in")
        filters[idx]["value"] = after.get("value", filters[idx].get("value"))
        return dsl
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/optimizer/rules/test_filter.py -v -k f006`
Expected: PASS(两个 F006 测试)

- [ ] **Step 5: 跑全部 filter 规则测试确认无回归**

Run: `pytest tests/unit/optimizer/rules/test_filter.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nl2dsl/optimizer/rules/filter.py tests/unit/optimizer/rules/test_filter.py
git commit -m "feat(optimizer): F006 like on 枚举维度改 in"
```

---

## Task 3: builder like 通配符分流 + semantic_config 注入

**Files:**
- Modify: `nl2dsl/sql_engine/builder.py`
- Modify: `nl2dsl/engine.py:228`
- Modify: `nl2dsl/api_factory.py:572,585`
- Test: `tests/unit/test_sql_builder.py`

**Interfaces:**
- Consumes: `SemanticConfig.get_selectivity(dimension)`、`is_indexed(dimension)`(Task 1)
- Produces: `SQLBuilder.__init__` 新增 `semantic_config: SemanticConfig | None = None` 参数;like 分支按 `indexed`+`selectivity` 决定通配符

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_sql_builder.py` 末尾追加(若文件顶部无以下 import 则补):

```python
def test_like_prefix_match_for_indexed_high_selectivity():
    """indexed + high selectivity 列:like 编译为前缀匹配 'val%'(走索引)。"""
    from nl2dsl.sql_engine.builder import SQLBuilder
    from nl2dsl.optimizer.context import SemanticConfig
    from sqlalchemy import create_engine, MetaData, Table, Column, String, Date

    engine = create_engine("sqlite:///:memory:")
    meta = MetaData()
    Table("order_fact", meta, Column("order_date", Date), Column("product_name", String))
    meta.create_all(engine)

    config = SemanticConfig(
        dimensions={
            "order_date": {"column": "order_date", "type": "date", "selectivity": "high", "indexed": True},
        }
    )
    builder = SQLBuilder(
        engine, {"orders": "order_fact"}, {"orders": {"table": "order_fact"}},
        {"order_date": "order_date"}, {}, {}, semantic_config=config,
    )
    from nl2dsl.dsl.models import DSL, Filter
    dsl = DSL(data_source="orders", filters=[Filter(field="order_date", operator="like", value="2026-07")])
    sql = builder.build(dsl)
    assert "order_date LIKE '2026-07%'" in sql
    assert "%2026-07%" not in sql


def test_like_full_match_for_unindexed_text():
    """无索引文本列:like 保持全模糊 '%val%'。"""
    from nl2dsl.sql_engine.builder import SQLBuilder
    from nl2dsl.optimizer.context import SemanticConfig
    from sqlalchemy import create_engine, MetaData, Table, Column, String

    engine = create_engine("sqlite:///:memory:")
    meta = MetaData()
    Table("order_fact", meta, Column("product_name", String))
    meta.create_all(engine)

    config = SemanticConfig(
        dimensions={
            "product_name": {"column": "product_name", "type": "string", "selectivity": "high", "indexed": False},
        }
    )
    builder = SQLBuilder(
        engine, {"orders": "order_fact"}, {"orders": {"table": "order_fact"}},
        {"product_name": "product_name"}, {}, {}, semantic_config=config,
    )
    from nl2dsl.dsl.models import DSL, Filter
    dsl = DSL(data_source="orders", filters=[Filter(field="product_name", operator="like", value="手机")])
    sql = builder.build(dsl)
    assert "product_name LIKE '%手机%'" in sql


def test_like_default_full_match_without_stats():
    """无统计信息时:like 退回当前行为 '%val%'(向后兼容)。"""
    from nl2dsl.sql_engine.builder import SQLBuilder
    from sqlalchemy import create_engine, MetaData, Table, Column, String

    engine = create_engine("sqlite:///:memory:")
    meta = MetaData()
    Table("order_fact", meta, Column("product_name", String))
    meta.create_all(engine)

    builder = SQLBuilder(
        engine, {"orders": "order_fact"}, {"orders": {"table": "order_fact"}},
        {"product_name": "product_name"}, {}, {},
        # 不传 semantic_config
    )
    from nl2dsl.dsl.models import DSL, Filter
    dsl = DSL(data_source="orders", filters=[Filter(field="product_name", operator="like", value="手机")])
    sql = builder.build(dsl)
    assert "product_name LIKE '%手机%'" in sql
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_sql_builder.py::test_like_prefix_match_for_indexed_high_selectivity -v`
Expected: FAIL(like 仍是 `%val%`,且 `semantic_config` 参数未定义 → TypeError)

- [ ] **Step 3: builder 构造函数加 semantic_config 参数**

在 `nl2dsl/sql_engine/builder.py` 修改 `SQLBuilder.__init__` 签名(当前 `builder.py:12`),在 `value_maps` 参数后加 `semantic_config`:

```python
class SQLBuilder:
    def __init__(self, engine, table_mapping: dict[str, str], data_sources: dict | None = None,
                 dimension_mapping: dict[str, str] | None = None, metrics: dict | None = None,
                 value_maps: dict[str, dict] | None = None, semantic_config=None):
        self._engine = engine
        self._metadata = MetaData()
        self._metadata.reflect(bind=engine)
        self._table_mapping = table_mapping
        self._data_sources = data_sources or {}
        self._dimension_mapping = dimension_mapping or {}
        self._metrics = metrics or {}
        self._value_maps = value_maps or {}
        self._semantic_config = semantic_config
```

在类中加两个辅助方法(放在 `_metric_expr` 之后):

```python
    def _get_selectivity(self, field: str) -> str | None:
        """Return selectivity for a dimension, or None if no semantic_config."""
        if self._semantic_config is None:
            return None
        return self._semantic_config.get_selectivity(field)

    def _is_indexed(self, field: str) -> bool:
        """Return whether a dimension is indexed, False if no semantic_config."""
        if self._semantic_config is None:
            return False
        return self._semantic_config.is_indexed(field)
```

- [ ] **Step 4: 实现 like 通配符分流**

在 `nl2dsl/sql_engine/builder.py` 修改 `_build_leaf_condition` 的 `like` 分支(当前 `builder.py:164-165`):

```python
        elif f.operator == "like":
            selectivity = self._get_selectivity(f.field)
            indexed = self._is_indexed(f.field)
            if indexed and selectivity == "high":
                # 高选择性 + 有索引:前缀匹配,走索引
                return col.like(f"{f.value}%")
            else:
                # 低选择性/无索引/缺省:全模糊(保持语义/向后兼容)
                return col.like(f"%{f.value}%")
```

- [ ] **Step 5: 实例化处传 semantic_config**

修改 `nl2dsl/engine.py:228`(在 `# 5. SQLBuilder` 段),先构造 SemanticConfig 再传入:

```python
            # 5. SQLBuilder
            from nl2dsl.optimizer.context import SemanticConfig
            semantic_config = SemanticConfig(
                metrics=registry.metrics,
                dimensions=registry.dimensions,
                data_sources=registry.data_sources,
            )
            tm = {k: v.get("table", k) for k, v in registry.data_sources.items()}
            ds = {k: v for k, v in registry.data_sources.items()}
            dm = {k: v.get("column", k) for k, v in registry.dimensions.items()}
            vmaps = {
                k: v.get("value_map")
                for k, v in registry.dimensions.items()
                if v.get("value_map")
            }
            sql_builder = SQLBuilder(db, tm, ds, dm, registry.metrics, vmaps, semantic_config=semantic_config)
```

修改 `nl2dsl/api_factory.py:572-579`(第一处实例化),在 SQLBuilder 调用末尾加 `semantic_config`:

```python
            from nl2dsl.optimizer.context import SemanticConfig
            _sc = SemanticConfig.from_registry_dict(registry_dict)
            _nl2dsl_engine.register("sql_builder", SQLBuilder(
                _db_engine,
                {k: v.get("table", k) for k, v in registry_dict.get("data_sources", {}).items()},
                registry_dict.get("data_sources", {}),
                {k: v.get("column", k) for k, v in registry_dict.get("dimensions", {}).items()},
                registry_dict.get("metrics", {}),
                _extract_value_maps(registry_dict.get("dimensions", {})),
                semantic_config=_sc,
            ))
```

修改 `nl2dsl/api_factory.py:585-592`(第二处实例化),同样加 `semantic_config`:

```python
                from nl2dsl.optimizer.context import SemanticConfig
                _sc = SemanticConfig.from_registry_dict(_default_registry)
                _nl2dsl_engine.register("sql_builder", SQLBuilder(
                    engine,
                    {k: v.get("table", k) for k, v in _default_registry.get("data_sources", {}).items()},
                    _default_registry.get("data_sources", {}),
                    {k: v.get("column", k) for k, v in _default_registry.get("dimensions", {}).items()},
                    _default_registry.get("metrics", {}),
                    _extract_value_maps(_default_registry.get("dimensions", {})),
                    semantic_config=_sc,
                ))
```

- [ ] **Step 6: 跑测试确认通过**

Run: `pytest tests/unit/test_sql_builder.py -v -k like`
Expected: PASS(三个 like 测试)

- [ ] **Step 7: 跑全部 builder 测试确认无回归**

Run: `pytest tests/unit/test_sql_builder.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add nl2dsl/sql_engine/builder.py nl2dsl/engine.py nl2dsl/api_factory.py tests/unit/test_sql_builder.py
git commit -m "feat(builder): like 按 selectivity/indexed 分流通配符,注入 semantic_config"
```

---

## Task 4: builder filter 值类型对齐

**Files:**
- Modify: `nl2dsl/sql_engine/builder.py`
- Test: `tests/unit/test_sql_builder.py`

**Interfaces:**
- Consumes: `col.type`(SQLAlchemy reflect 已提供,无新依赖)
- Produces: `SQLBuilder._align_value_type(col, field, value) -> value`,在 `_build_leaf_condition` 各分支前统一对齐

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_sql_builder.py` 末尾追加:

```python
def test_filter_value_type_aligned_numeric_string_to_int():
    """Integer 列收到数字字符串 '100' → 无损转 int,命中索引。"""
    from nl2dsl.sql_engine.builder import SQLBuilder
    from sqlalchemy import create_engine, MetaData, Table, Column, Integer

    engine = create_engine("sqlite:///:memory:")
    meta = MetaData()
    Table("order_fact", meta, Column("amount", Integer))
    meta.create_all(engine)

    builder = SQLBuilder(
        engine, {"orders": "order_fact"}, {"orders": {"table": "order_fact"}},
        {"amount": "amount"}, {}, {},
    )
    from nl2dsl.dsl.models import DSL, Filter
    dsl = DSL(data_source="orders", filters=[Filter(field="amount", operator="=", value="100")])
    sql = builder.build(dsl)
    # literal_binds 内联:int 100 不带引号
    assert "amount = 100" in sql
    assert "amount = '100'" not in sql


def test_filter_value_type_aligned_number_to_str_warns():
    """String 列收到数字 123 → 显式转 str '123'(有损但显式)。"""
    from nl2dsl.sql_engine.builder import SQLBuilder
    from sqlalchemy import create_engine, MetaData, Table, Column, String
    import logging

    engine = create_engine("sqlite:///:memory:")
    meta = MetaData()
    Table("order_fact", meta, Column("product_name", String))
    meta.create_all(engine)

    builder = SQLBuilder(
        engine, {"orders": "order_fact"}, {"orders": {"table": "order_fact"}},
        {"product_name": "product_name"}, {}, {},
    )
    from nl2dsl.dsl.models import DSL, Filter
    dsl = DSL(data_source="orders", filters=[Filter(field="product_name", operator="=", value=123)])
    sql = builder.build(dsl)
    assert "product_name = '123'" in sql
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_sql_builder.py::test_filter_value_type_aligned_numeric_string_to_int -v`
Expected: FAIL(`amount = '100'` 带引号,未转 int)

- [ ] **Step 3: 实现 _align_value_type 并改造 _build_leaf_condition**

在 `nl2dsl/sql_engine/builder.py` 顶部 import 区确认有 `import logging` 和 `from sqlalchemy import Integer, String, Numeric, Float`(若缺则补;现有 import 行已含 `select, func, and_, or_, not_, desc, asc, text, column, literal, Table, MetaData`,把 `Integer, String, Numeric, Float` 加进去)。

在类中加 `logger` 和 `_align_value_type` 方法(放在 `_is_indexed` 之后):

```python
import logging
logger = logging.getLogger(__name__)
```

(注:若文件已有 logger,复用;否则在模块顶部加。)

```python
    def _align_value_type(self, col, field: str, value):
        """Align filter value type to column type.

        Lossless cast (numeric column + numeric string) → int/float, hits index.
        Lossy but explicit (string column + number) → str + warn.
        Other mismatches → passthrough (DB handles, warn logged by caller if needed).
        """
        from sqlalchemy import Integer, Numeric, Float, String
        col_type = col.type
        # Lossless: numeric column + numeric string
        if isinstance(col_type, (Integer, Numeric, Float)) and isinstance(value, str) and not isinstance(value, bool):
            try:
                if isinstance(col_type, Integer):
                    return int(value)
                return float(value)
            except (ValueError, TypeError):
                logger.warning("Filter value %r not numeric for column '%s'", value, field)
                return value
        # Lossy: string column + number → str (explicit, warn)
        if isinstance(col_type, String) and isinstance(value, (int, float)) and not isinstance(value, bool):
            logger.warning("String column '%s' got numeric value %r, coercing to str", field, value)
            return str(value)
        return value
```

改造 `_build_leaf_condition`(当前 `builder.py:147-174`),在 `col = self._resolve_column(...)` 之后插入类型对齐,并把各分支的 `f.value` / `self._translate_filter_value(f.field, f.value)` 统一改为先用 `aligned`:

```python
    def _build_leaf_condition(self, tables: dict[str, object], f) -> object:
        """Build a single filter condition (leaf node)."""
        col = self._resolve_column(tables, f.field)
        # value_map 翻译(语义值→物理编码)→ 类型对齐(列类型)
        raw_value = self._translate_filter_value(f.field, f.value)
        aligned = self._align_value_type(col, f.field, raw_value)
        if f.operator == "=":
            return col == aligned
        elif f.operator == "!=":
            return col != aligned
        elif f.operator == ">":
            return col > aligned
        elif f.operator == "<":
            return col < aligned
        elif f.operator == ">=":
            return col >= aligned
        elif f.operator == "<=":
            return col <= aligned
        elif f.operator == "in":
            return col.in_(aligned if isinstance(aligned, list) else [aligned])
        elif f.operator == "like":
            selectivity = self._get_selectivity(f.field)
            indexed = self._is_indexed(f.field)
            if indexed and selectivity == "high":
                return col.like(f"{aligned}%")
            else:
                return col.like(f"%{aligned}%")
        elif f.operator == "between":
            val = aligned
            if isinstance(val, (list, tuple)) and len(val) == 2:
                return col.between(val[0], val[1])
            raise ValidationError(f"'between' requires [min, max] list, got {val!r}")
        elif f.operator == "is_null":
            return col.is_(None)
        else:
            raise ValidationError(f"Unknown operator: {f.operator}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/test_sql_builder.py -v -k "type_aligned"`
Expected: PASS(两个类型对齐测试)

- [ ] **Step 5: 跑全部 builder 测试确认无回归**

Run: `pytest tests/unit/test_sql_builder.py -v`
Expected: PASS(类型对齐改造可能影响既有用例,若有失败检查 value 类型是否被对齐改变)

- [ ] **Step 6: Commit**

```bash
git add nl2dsl/sql_engine/builder.py tests/unit/test_sql_builder.py
git commit -m "feat(builder): filter 值类型对齐(无损 cast + 有损告警)"
```

---

## Task 5: builder join 按 size 重排

**Files:**
- Modify: `nl2dsl/sql_engine/builder.py`
- Test: `tests/unit/test_sql_builder.py`

**Interfaces:**
- Consumes: `self._data_sources`(已注入,含 `size` 字段,无新依赖)
- Produces: `_determine_required_joins` 末尾按 `size` 保守重排(仅无跨依赖时)

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_sql_builder.py` 末尾追加:

```python
def test_join_reordered_small_drives_large():
    """无跨依赖时:small 表排在前(驱动),large 排在后。"""
    from nl2dsl.sql_engine.builder import SQLBuilder
    from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String

    engine = create_engine("sqlite:///:memory:")
    meta = MetaData()
    Table("order_fact", meta, Column("product_id", Integer), Column("customer_id", Integer))
    Table("product_dim", meta, Column("product_id", Integer), Column("product_name", String))
    Table("customer_dim", meta, Column("customer_id", Integer), Column("customer_name", String))
    meta.create_all(engine)

    # 两个独立 join(无跨依赖:on_field 不含 ".")
    data_sources = {
        "orders": {
            "table": "order_fact", "size": "large",
            "joins": {
                "product_dim": {"on": "product_id", "type": "left", "alias": "p"},
                "customer_dim": {"on": "customer_id", "type": "left", "alias": "c"},
            },
        },
        "product_dim": {"table": "product_dim", "size": "medium"},
        "customer_dim": {"table": "customer_dim", "size": "small"},
    }
    builder = SQLBuilder(
        engine, {"orders": "order_fact"}, data_sources,
        {"product_name": "product_name"}, {}, {},
    )
    from nl2dsl.dsl.models import DSL, Aggregation
    # 引用两个 join 表的列,触发两个 join
    dsl = DSL(
        data_source="orders",
        metrics=[Aggregation(func="sum", field="product_id", alias="m")],
        dimensions=["product_name"],
    )
    sql = builder.build(dsl)
    # customer_dim(small) 应在 product_dim(medium) 之前
    c_pos = sql.lower().find("customer_dim")
    p_pos = sql.lower().find("product_dim")
    assert c_pos != -1 and p_pos != -1
    assert c_pos < p_pos, f"small 应驱动,但 SQL 顺序: {sql}"


def test_join_not_reordered_with_cross_dependency():
    """有跨依赖(supplier_dim on p.supplier_id)时:保持依赖顺序,不重排。"""
    from nl2dsl.sql_engine.builder import SQLBuilder
    from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String

    engine = create_engine("sqlite:///:memory:")
    meta = MetaData()
    Table("order_fact", meta, Column("product_id", Integer))
    Table("product_dim", meta, Column("product_id", Integer), Column("supplier_id", Integer))
    Table("supplier_dim", meta, Column("supplier_id", Integer), Column("supplier_name", String))
    meta.create_all(engine)

    data_sources = {
        "orders": {
            "table": "order_fact", "size": "large",
            "joins": {
                "product_dim": {"on": "product_id", "type": "left", "alias": "p"},
                "supplier_dim": {"on": "p.supplier_id", "type": "left", "alias": "s"},
            },
        },
        "product_dim": {"table": "product_dim", "size": "medium"},
        "supplier_dim": {"table": "supplier_dim", "size": "small"},
    }
    builder = SQLBuilder(
        engine, {"orders": "order_fact"}, data_sources,
        {"supplier_name": "supplier_name"}, {}, {},
    )
    from nl2dsl.dsl.models import DSL
    dsl = DSL(data_source="orders", dimensions=["supplier_name"])
    sql = builder.build(dsl)
    # 依赖链:product_dim 必须在 supplier_dim 之前(on p.supplier_id)
    p_pos = sql.lower().find("product_dim")
    s_pos = sql.lower().find("supplier_dim")
    assert p_pos < s_pos, f"依赖链被破坏: {sql}"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_sql_builder.py::test_join_reordered_small_drives_large -v`
Expected: FAIL(当前按依赖顺序,customer_dim 可能在 product_dim 之后)

- [ ] **Step 3: 实现 join 按 size 保守重排**

在 `nl2dsl/sql_engine/builder.py` 的 `_determine_required_joins` 方法中,在 `return joins` 之前(当前 `builder.py:327` 附近)插入重排逻辑:

```python
        # 保守重排:仅当 join 之间无跨依赖(on_field 不含 ".")时,按 size 排序
        # small 在前(驱动),large 在后(被驱动);同等级保持原依赖顺序(稳定排序)
        if len(joins) > 1:
            has_cross_dependency = any(
                "." in (j.on_field or "") for j in joins
            )
            if not has_cross_dependency:
                size_order = {"small": 0, "medium": 1, "large": 2}
                joins.sort(
                    key=lambda j: size_order.get(self._get_size_for_join_table(j.table), 3)
                )

        return joins
```

在类中加辅助方法(放在 `_get_table_for_column` 之后):

```python
    def _get_size_for_join_table(self, table_name: str) -> str | None:
        """Return the size of the data_source whose physical table matches table_name."""
        for cfg in self._data_sources.values():
            if cfg.get("table") == table_name:
                return cfg.get("size")
        return None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/test_sql_builder.py -v -k "join_reordered or join_not_reordered"`
Expected: PASS(两个 join 重排测试)

- [ ] **Step 5: 跑全部 builder 测试确认无回归**

Run: `pytest tests/unit/test_sql_builder.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nl2dsl/sql_engine/builder.py tests/unit/test_sql_builder.py
git commit -m "feat(builder): join 按 size 保守重排(无跨依赖时 small 驱动 large)"
```

---

## Task 6: 评测用例 + 多域对齐

**Files:**
- Modify: `configs/bank_metrics.yaml`
- Modify: `tests/evaluation/dataset/`(加用例)
- Test: 端到端验证

**Interfaces:**
- Consumes: Task 1-5 全部产出

- [ ] **Step 1: bank_metrics.yaml 补统计字段**

打开 `configs/bank_metrics.yaml`,参照 Task 1 的 metrics.yaml 改法,给 `data_sources` 各源加 `size`(事实表如交易明细 `large`,维度表 `small`/`medium`),给 `dimensions` 各维度加 `selectivity`/`indexed`(交易日期 `high`+`true`,枚举如币种/渠道 `low`)。字段缺省不阻塞,优先给热点查询涉及的表/列补。

- [ ] **Step 2: 加评测用例**

在 `tests/evaluation/dataset/` 下参考现有用例文件格式(如 `ecommerce_cases.yaml` 或同级文件),追加覆盖三个优化点的用例:

```yaml
# 参照现有 dataset 文件的 schema 追加,以下为用例内容示意
- id: like_indexed_prefix_match
  query: "查订单日期是2026年7月开头的销售"
  expect:
    # like 应编译为前缀匹配(若 order_date indexed+high)
    sql_contains: "order_date LIKE '2026-07%'"
    sql_not_contains: "%2026-07%"

- id: join_small_drives_large
  query: "查各供应商名称的订单数"
  expect:
    # 多表 join 时,小表(supplier_dim)驱动
    # 验证审计 trace 中 SQL join 顺序(具体断言按现有评测框架能力)

- id: filter_type_alignment
  query: "查金额等于100的订单"
  expect:
    # 数值列收到字符串值应转 int
    sql_contains: "amount = 100"
    sql_not_contains: "amount = '100'"
```

(注:用例 schema 以现有 dataset 文件为准;若现有框架不支持 `sql_contains` 断言,改用等价断言字段。)

- [ ] **Step 3: 跑评测确认用例通过**

Run: `pytest tests/evaluation/ -v -k "like_indexed or join_small or filter_type"`
Expected: PASS(若评测框架 CLI 不同,改用 `nl2dsl-eval` 或项目既有评测入口)

- [ ] **Step 4: 跑全量测试确认无回归**

Run: `pytest tests/unit/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add configs/bank_metrics.yaml tests/evaluation/dataset/
git commit -m "test: 补统计驱动 SQL 调优评测用例 + 银行域字段对齐"
```

---

## Self-Review

**1. Spec coverage:**

| Spec 章节 | 对应 Task |
|----------|----------|
| §4 配置 Schema(size/selectivity/indexed) | Task 1 |
| §5 SemanticConfig getter | Task 1 |
| §6 F006 规则 | Task 2 |
| §7.1 like 通配符分流 | Task 3 |
| §7.2 filter 类型对齐 | Task 4 |
| §7.3 join 按 size 重排 | Task 5 |
| §8 向后兼容(字段可选) | Task 1(getter 缺省)+ Task 3(semantic_config 可选) |
| §8 多域对齐 | Task 6(bank_metrics) |
| §9 评测用例 | Task 6 |

无遗漏。

**2. Placeholder scan:** 无 TBD/TODO;Task 6 评测用例 schema 注明"以现有 dataset 文件为准"并给出示意 + 断言指引,因评测框架 schema 未在 spec 中固化,属合理指引非占位。

**3. Type consistency:**
- `get_size` / `get_selectivity` / `is_indexed`:Task 1 定义,Task 3 消费,签名一致
- `SQLBuilder.__init__` 的 `semantic_config` 参数:Task 3 定义,engine.py/api_factory.py 传参一致
- `_get_selectivity` / `_is_indexed` / `_align_value_type` / `_get_size_for_join_table`:命名在定义处与消费处一致
- F006 `fix()` 的 `location=f"filters[{i}]"` 与解析逻辑(parts[1] 为 idx)一致
- `_build_leaf_condition` 在 Task 3(like 分流)和 Task 4(全函数改造)中,Task 4 的版本是 superset,含 Task 3 的 like 逻辑

无类型/命名不一致。
