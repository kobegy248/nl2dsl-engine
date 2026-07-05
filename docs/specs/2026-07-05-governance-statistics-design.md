# 统计信息纳入治理层 + A/C 类 SQL 调优

> 状态:设计已确认,待编写实施计划
> 日期:2026-07-05
> 主题:将表/列统计信息作为治理层一等公民,驱动 SQL 语句级调优

---

## 1. 背景与动机

NL2DSL 是 Governance-Aware Semantic Query Engine。治理层(SemanticConfig)当前注册了三类元数据:

- **语义**(`metrics`/`dimensions`):指标表达式、维度列映射、枚举 value_map
- **治理**(`permissions`):行级权限、列级脱敏
- **数据源拓扑**(`data_sources`):表映射、join 路径

但**统计信息缺失**——表大小、列选择性、是否索引,这些数据物理特征没有注册。导致 SQL 语句级调优出现两类空白:

### A 类:SQL 写法正确性(不依赖统计信息,只需列类型)

- `like` 一律编译为 `col LIKE '%val%'`(`builder.py:165`),前导通配符导致索引必然失效
- filter 值类型与列类型不匹配时直接传入(如 INTEGER 列收到 `"100"`),触发 DB 隐式转换,索引失效

### C 类:统计驱动的粗优化(需要静态统计先验)

- join 按**依赖顺序**排列(`builder.py:299`),不按表大小,无法实现"小表驱动大表"
- like 能否走索引需要知道列是否有索引、选择性高低

### B 类:运行时 EXPLAIN 动态校正(本 spec 不做)

需要多方言 EXPLAIN 解析,拆为后续独立 spec。

### 为什么统计信息应该走治理层

与项目核心原则一致:

- **Semantic First**:指标/维度必须语义层注册,禁止自由文本、禁止发明未定义指标
- **Governance is authoritative**:权限策略是数据源真理,不是事后补丁

按同样逻辑,统计信息也是数据资产元数据,理应在治理层注册,查询引擎**消费**而非**探查**。当前 A/C 类优化做不了的根因不是"没有运行时探查能力",而是"治理层没注册统计信息"。

---

## 2. 设计目标与非目标

### 目标

1. 在治理层(`metrics.yaml`)注册表/列统计信息(定性等级)
2. SemanticConfig 暴露统计信息 getter
3. optimizer 新增规则:like 作用在枚举维度 → 改 `in`(DSL 层修正,可观测)
4. builder 消费统计信息做 SQL 编译决策:like 通配符方向、filter 类型对齐、join 按 size 重排

### 非目标(YAGNI / 拆分)

- ❌ B 类运行时 EXPLAIN 多方言解析 → 后续独立 spec
- ❌ 定量数值(row_count / cardinality 数值)→ 定性等级已足够 C 类
- ❌ 表级 `indexed_columns` 冗余字段 → dimension 级 `indexed` 已够
- ❌ 索引提示 / 强制索引 → 破坏方言无关性
- ❌ selectivity 参与 join 重排(同等级次级键)→ 第一版只按 size,见 §8

---

## 3. 设计决策汇总

| # | 决策 | 选择 |
|---|------|------|
| 1 | 实施范围 | 基建 + A/C 类(B 类动态 EXPLAIN 拆为后续独立 spec) |
| 2 | 统计粒度 | 定性等级(large/medium/small、high/medium/low) |
| 3 | 配置归属 | 并入 `metrics.yaml` 的 `data_sources`/`dimensions` 段 |
| 4 | 消费层 | 分层:optimizer 做 DSL 修正(可观测)+ builder 做 SQL 编译决策 |
| 5 | 类型对齐策略 | 安全转换 + 告警(无损 cast,有损告警放行) |
| 6 | like on 枚举 | 改 `in`(容错多值,单值也用 `in`) |
| 7 | join 重排 | 只按 `size`(small 驱动 large),同等级保持依赖顺序 |
| 8 | 命名 | `size` / `selectivity` / `indexed`,弃用 `cardinality`(避免与列基数概念混) |

---

## 4. 配置 Schema

并入 `metrics.yaml`,三个新字段**全部可选**,缺省时 builder/optimizer 退回当前行为(忠实编译,不优化)。

### 4.1 `data_sources` 段新增 `size`

```yaml
data_sources:
  orders:
    table: order_fact
    size: large              # large | medium | small —— 表行数等级,join 重排依据
    metrics: [...]
    dimensions: [...]
    joins: {...}
  products:
    table: product_dim
    size: medium
    metrics: [...]
    dimensions: [...]
  suppliers:
    table: supplier_dim
    size: small              # 维度小表,join 时作驱动
    metrics: []
    dimensions: [supplier_name]
```

**语义**:
- `large`:事实大表,join 时被驱动
- `medium`:中等规模
- `small`:维度小表,join 时作驱动表
- 缺省:不参与 join 重排,保持依赖顺序

### 4.2 `dimensions` 段新增 `selectivity` 与 `indexed`

```yaml
dimensions:
  region:
    column: region
    type: string
    selectivity: low          # high | medium | low —— 该列做过滤条件时的选择性
    indexed: true             # 该列是否建索引
    value_map:
      华东: HD
      华南: HN
  product_name:
    column: product_name
    type: string
    selectivity: high         # 高基数文本
    indexed: false
  order_date:
    column: order_date
    type: date
    selectivity: high
    indexed: true
  customer_type:
    column: customer_type
    type: string
    selectivity: low
    indexed: false
    value_map:
      VIP: vip
      新客: new
      老客: old
```

**语义**:
- `selectivity`:该列作为过滤条件时的选择性等级
  - `high`:过滤后剩余行少(如 user_id、date、名称),作过滤能大幅缩小结果集
  - `low`:过滤后剩余行多(如性别、地区、枚举)
  - `medium`:介于两者
  - 缺省:按 `low` 处理(保守,不影响 like 分流的兜底分支)
- `indexed`:该列是否建索引
  - `true`:有索引,like 可考虑前缀匹配走索引
  - `false` / 缺省:无索引

### 4.3 字段命名理由

弃用 `cardinality`:该词在 DB 语境通常指"列的 distinct 值数",用在表上指"表大小等级"会产生歧义。改用:

- `size`(表)—— 表大小等级,直观
- `selectivity`(列)—— DB 标准术语,指过滤选择性,准确

`size`(表)与 `selectivity`(列)概念彻底分离,不会混淆。

---

## 5. SemanticConfig getter

在 `nl2dsl/optimizer/context.py` 的 `SemanticConfig` 新增三个方法,与现有 `get_value_map()` / `get_dimension_type()` 同模式,零新机制:

```python
def get_size(self, data_source: str) -> str | None:
    """返回 data_source 的表大小等级:large/medium/small,缺省 None。"""
    ds = self.data_sources.get(data_source, {})
    return ds.get("size")

def get_selectivity(self, dimension: str) -> str | None:
    """返回 dimension 的过滤选择性等级:high/medium/low,缺省 None(按 low 处理)。"""
    d = self.dimensions.get(dimension, {})
    return d.get("selectivity")

def is_indexed(self, dimension: str) -> bool:
    """返回 dimension 是否建索引,缺省 False。"""
    d = self.dimensions.get(dimension, {})
    return bool(d.get("indexed", False))
```

---

## 6. optimizer 层:DSL 修正规则

### F006 LikeOnEnumDimension

- **error_code**: F006
- **category**: Filter
- **priority**: 3(P3 Consistency)
- **severity**: Fix
- **confidence**: high
- **auto_fixable**: True
- **is_fatal**: False

**check() 逻辑**:
遍历 `dsl.filters`(flat list 或 tree),对每个 `operator == "like"` 的叶子:
- 取 `field`,查 `context.semantic_config.get_value_map(field)`
- 若该维度有 `value_map`(枚举维度),触发修正

**fix() 逻辑**:
- `like` → `in`
- 值保持原值(单值时包装为 `[value]`,多值候选时按需拆分)
- 统一用 `in` 容错:即使单值也用 `in`,语义统一且容错多值匹配

**理由**:
枚举维度本应精确匹配,`like` 是 LLM 误用。改 `in` 后:
- 命中索引(等值而非模糊)
- 进 `OptimizationReport` 可观测、可审计(符合 Explainability First)
- builder 层不再需要处理"枚举维度的 like"这一矛盾场景

**不触发的情况**:
- `field` 无 `value_map`(如 `product_name` 纯文本)→ 不改,交给 builder 按通配符规则处理

---

## 7. builder 层:SQL 编译决策

`nl2dsl/sql_engine/builder.py` 消费统计信息。builder 需要访问 SemanticConfig 的统计 getter——通过构造函数注入 `semantic_config`(或单独的统计查询接口),与现有 `dimension_mapping` / `value_maps` 注入方式一致。

### 7.1 like 通配符方向

修改 `_build_leaf_condition` 的 `like` 分支(当前 `builder.py:164-165`):

```python
elif f.operator == "like":
    selectivity = self._get_selectivity(f.field)   # high/medium/low/None
    indexed = self._is_indexed(f.field)            # bool
    if indexed and selectivity == "high":
        # 高选择性 + 有索引:前缀匹配,走索引
        return col.like(f"{f.value}%")
    else:
        # 低选择性/无索引/文本:全模糊(保持语义)
        return col.like(f"%{f.value}%")
```

**注**:枚举维度的 like 已被 F006 改成 `in`,不会走到此分支的枚举场景;此分支处理的是纯文本维度(`product_name` 等)。

**判定表**:

| 条件 | 编译为 | 理由 |
|------|--------|------|
| `indexed=true` 且 `selectivity=high` | `col LIKE 'val%'` | 前缀匹配,走索引 |
| `indexed=false` 或 `selectivity≠high` | `col LIKE '%val%'` | 无索引可用,保持全模糊语义 |
| 字段缺省统计信息 | `col LIKE '%val%'` | 退回当前行为 |

### 7.2 filter 类型对齐

修改 `_build_leaf_condition`,在生成比较条件前按列类型对齐值。依赖 builder 已有的 `_metadata.reflect`(`builder.py:15`),`col.type` 可直接获取,无新依赖:

```python
col = self._resolve_column(tables, f.field)
aligned_value = self._align_value_type(col, f.field, f.value)
# 后续用 aligned_value 替代 f.value 生成条件
```

**`_align_value_type` 逻辑**:

| 列类型 | 值类型 | 处理 | 级别 |
|--------|--------|------|------|
| Integer / Numeric | str 且是数字字符串(`"100"`) | `int(value)` / `float(value)` | 无损转换 |
| Integer / Numeric | str 非数字(`"abc"`) | 告警,原样传入 | 有损,记录 warning |
| String | int / float | `str(value)` + 告警 | 有损,显式转,记录 warning |
| Date | str | 原样传入(DB 解析) | 交 DB |
| 其他不匹配 | — | 告警放行 | 记录 trace |

**安全转换边界**(无损才转):
- 数值列 ↔ 数字字符串:无损,显式 cast 保证命中索引
- 字符串列 ↔ 数字:有损(语义可能变),显式转 str 但告警
- 其他:不转,告警

**与 value_map 的关系**:`_translate_filter_value` 已处理枚举值翻译(`builder.py:129`),类型对齐在其后执行,顺序为:语义值 → 物理编码(value_map)→ 类型对齐(列类型)。

### 7.3 join 按 size 重排

修改 `_determine_required_joins`(`builder.py:231`),在现有依赖链约束下按 `size` 排序:

**约束优先级**:
1. **依赖链优先**:`resolve_deps` 已保证(supplier_dim on `p.supplier_id` 必须在 product_dim 之后)。依赖链**不被 size 破坏**。
2. **size 次之**:在依赖链允许的范围内,`small` 在前(驱动),`large` 在后(被驱动)。
3. **同等级保持现状**:同 size 等级的 join 之间保持依赖顺序,不引入次级键。

**第一版实现(保守重排)**:
- 现有 `add_join` 按依赖顺序递归构建 joins 列表
- 重排**只对无依赖关系的 join** 生效:按 `size` 等级(`small` < `medium` < `large` < None)做稳定排序,同等级保持原依赖顺序
- 有依赖关系的 join 链(如 supplier_dim on `p.supplier_id`)保持原序,**不被 size 破坏**
- 这覆盖最常见的"多张独立维度小表 join 一张大事实表"场景,且不冒破坏依赖的风险

**缺省行为**:所有 data_source 都没 `size` 时,排序退化为原依赖顺序(现状)。

---

## 8. 向后兼容与多域

### 向后兼容

- 三个新字段(`size` / `selectivity` / `indexed`)**全部可选**
- 现有 `metrics.yaml` 不改动也能运行:builder/optimizer 遇到缺省值退回当前行为
- getter 返回 None / False 时,消费逻辑走兜底分支(保持现状编译方式)

### 多域对齐

- 项目支持多域(`metrics.yaml` + `bank_metrics.yaml`)
- 新字段在两个域都适用,但**不强制一次性补全**
- 建议先给电商域 `orders` / `region` / `order_date` 等热点表补字段,银行域随用随补
- 缺省字段时退回当前行为,不阻塞

### Join 重排的保守策略(限制说明)

`SQLBuilder` 的 join 重排是**保守**设计,仅同时满足以下两个条件时才会按 `size` 排序(small 驱动 large):

1. **join 表必须注册为独立 `data_source` 并标注 `size`** — builder 通过物理表名反查 `_data_sources` 中匹配 `table` 字段的条目获取 `size`;未注册的 join 表 `size` 为 None,排序回退到固定权重 3(等同 large),与同等级 join 保持原依赖顺序(稳定排序)。
2. **整条 join 链无跨依赖** — 任意一个 join 的 `on_field` 含 `.`(形如 `p.supplier_id`,即依赖前一个 join 的别名)时,整条链保持依赖顺序不重排。

> 这意味着:一个跨依赖会**禁用整条链**的重排(而非仅跳过该 join)。这是有意的保守策略——避免破坏依赖顺序导致 SQL 语义错误。

- **电商域 `orders`**:join 链含 `supplier_dim on p.supplier_id`(跨依赖),重排被跳过——符合预期。
- **银行域 `customer_accounts`**:join `t_cif_base`(经 `customers` data_source 注册,`size: medium`)与 `t_org_hier`(经 `org_hierarchy` data_source 注册,`size: small`),无跨依赖——重排生效,`t_org_hier`(small)排到 `t_cif_base`(medium)之前。
- **银行域 `transactions` / `agreements`**:join 链中的 `t_chl_mapping` / `t_txn_type_dict` / `t_prod_info` 等尚未注册为独立 data_source,`size` 为 None,重排对这些表无实际效果(回退权重 3,稳定排序保持原顺序)。如需启用,按 `org_hierarchy` 的模式补独立 data_source 条目即可。

### 配置加载

`SemanticRegistry.load`(`semantic/registry.py`)无需改动——它已透传 `data_sources` / `dimensions` 整段 dict,新字段自动随加载。`SemanticConfig.from_registry_dict` 同理。

---

## 9. 测试策略

### 单元测试

| 测试点 | 文件 | 验证 |
|--------|------|------|
| 配置加载 | `tests/unit/optimizer/test_context.py` | 新字段缺省不 break;有值时 getter 正确返回 |
| F006 规则 | `tests/unit/optimizer/test_filter_rules.py` | like on `region`(有 value_map)→ 改 `in`;on `product_name`(无 value_map)→ 不触发 |
| like 通配符分流 | `tests/unit/sql_engine/test_builder.py` | `order_date`(indexed+high)→ `val%`;`product_name`(无索引)→ `%val%` |
| 类型对齐 | `tests/unit/sql_engine/test_builder.py` | Integer 列 + `"100"` → int;String 列 + `123` → str + 告警;非数字字符串 → 告警放行 |
| join 重排 | `tests/unit/sql_engine/test_builder.py` | small 驱动 large;supplier_dim 仍在 product_dim 之后(依赖不破);缺省 size 退回依赖顺序 |
| 向后兼容 | `tests/unit/sql_engine/test_builder.py` | 无统计字段的 metrics.yaml 仍正常构建 SQL |

### 集成测试

| 测试点 | 验证 |
|--------|------|
| 端到端 like 优化 | NL "查商品名包含手机" → 生成 `LIKE '手机%'` 或 `%手机%` 视索引而定 |
| 端到端 join 优化 | 多表 join 查询 → 审计 trace 中 SQL 的 join 顺序符合 size 重排 |
| F006 端到端 | NL "查华东地区的销售" → DSL 中 region 的 like(若有)被改 `in`,report 记录 F006 |

### 评测用例

按 CLAUDE.md 工程规则 6「所有新增功能必须添加评测用例」:
- 在 `tests/evaluation/dataset/` 新增覆盖 like 模糊匹配、多表 join、类型边界场景的用例
- 对比优化前后 SQL(like 通配符、join 顺序)与执行结果正确性

---

## 10. 不做(YAGNI)

| 项 | 原因 |
|----|------|
| B 类运行时 EXPLAIN 多方言解析 | 范围大,需解析 7 种方言 EXPLAIN 输出,拆为后续独立 spec |
| 定量数值(row_count / cardinality 数值) | 定性等级已足够 C 类粗优化;定量值易过时,需同步机制,属 B 类范畴 |
| 表级 `indexed_columns` 冗余字段 | dimension 级 `indexed` 已覆盖判断需求 |
| 索引提示 / 强制索引 | 破坏方言无关性,且 DB 引擎已负责 |
| selectivity 参与 join 重排(同等级次级键) | 第一版 YAGNI;需关联 filter→dimension→所属表,逻辑复杂且接近 B 类估算范畴,留作后续增强 |
| 自动统计信息同步(ANALYZE / 采样) | 定性等级是静态语义级,建模时确定,不需要运行时同步 |

---

## 11. 后续演进

本 spec 落地后,后续可独立推进:

1. **B 类动态 EXPLAIN 多方言化**:升级 `query/sandbox.py` 的 `_explain`(当前 SQLite 专属粗糙启发式)为多方言 EXPLAIN 解析器,提供运行时行数估算,与治理层静态 `size` 互补
2. **selectivity 参与 join 重排**:在 size 同等级时,以"带 high selectivity 过滤条件的表优先驱动"为次级键
3. **定量统计(可选)**:若静态等级不足,引入 `statistics.yaml` 存定量数值 + 后台 ANALYZE 同步

---

## 12. 与现有架构对齐

| 现有机制 | 本 spec 对齐方式 |
|---------|----------------|
| SemanticConfig 从 metrics.yaml 加载 | 新字段随 data_sources/dimensions 段透传,零加载改动 |
| SemanticRegistry.load 透传 dict | 无需改动 |
| optimizer 规则注册(RuleRegistry) | F006 用 `@RuleRegistry.register` 装饰器,与 F001-F005 同模式 |
| builder 构造函数注入 dimension_mapping/value_maps | 新增 semantic_config 注入(或统计 getter 接口),同模式 |
| OptimizationReport 记录 Fix | F006 的 fix 进 fixes_applied,可观测 |
| 多域配置(metrics.yaml / bank_metrics.yaml) | 字段可选,两域兼容 |
