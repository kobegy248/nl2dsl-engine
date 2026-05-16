# 10. 语义层设计

## 10.1 指标注册

采用 YAML 定义指标和维度：

```yaml
# configs/metrics.yaml
metrics:
  sales_amount:
    expr: SUM(order_amount)
    description: "销售额"
    unit: "CNY"

  gmv:
    expr: SUM(pay_amount)
    description: "GMV"
    unit: "CNY"

dimensions:
  product_name:
    column: product_name
    description: "产品名称"

  region:
    column: region
    description: "地区"
    values: ["华东", "华南", "华北", "西南", "西北", "东北"]

  gender:
    column: gender_code
    description: "性别"
    value_map:
      "男性": 1
      "女性": 2
      "未知": 0

data_sources:
  orders:
    table: order_fact
    metrics: [sales_amount, gmv]
    dimensions: [product_name, region, gender, order_date]
    time_field: order_date
```

## 10.2 语义层生成与维护

语义层配置不是纯人工编写，而是**自动提取 + 人工补充**的结合。

### 10.2.1 生成时机

| 时机 | 触发方式 | 生成内容 |
|------|---------|---------|
| 数据库就绪后 | 执行 `scripts/init_semantic.py` | 从数据库元数据生成基础 `schema.yaml` |
| 数据库结构变更 | 检测 DDL 变更 | 自动对比并提示新增/删除的字段 |
| 人工维护 | 编辑 `configs/*.yaml` | 补充业务指标、描述、枚举映射 |

### 10.2.2 自动生成流程

```
连接数据库
  ↓
提取所有表名、列名、类型、COMMENT
  ↓
生成基础 schema.yaml（表结构）
  ↓
人工补充：
  - 业务指标定义（metrics）
  - 字段描述（无 COMMENT 的字段）
  - 枚举值映射（value_map）
  - 数据源关联关系
  ↓
写入 configs/metrics.yaml
  ↓
加载到内存缓存 + 写入向量库
```

### 10.2.3 自动提取 vs 人工补充

| 内容 | 来源 | 能否自动生成 |
|------|------|------------|
| 表名、列名、类型 | 数据库元数据 | 完全自动 |
| 字段 COMMENT | 数据库元数据 | 如果有 COMMENT |
| 字段描述（无 COMMENT） | AI 辅助 | 基于字段名推断，需人工校验 |
| 业务指标（销售额、GMV） | 业务定义 | **必须人工定义** |
| 枚举值映射 | 业务定义 | 可从字典表同步 |
| 数据源关联（Join） | 业务定义 | **必须人工定义** |

### 10.2.4 AI 辅助生成字段描述

对于没有 COMMENT 的字段，使用 LLM 基于字段名和类型自动生成描述：

```
输入: 字段名=user_name, 类型=VARCHAR(50)
输出: "用户姓名/昵称"

输入: 字段名=is_vip, 类型=BOOLEAN
输出: "是否 VIP 用户"
```

**注意：** AI 生成的描述仅供参考，必须人工审核后才能用于生产。

### 10.2.5 COMMENT 质量检测与增强

数据库 COMMENT 质量参差不齐，常见问题：

| 问题类型 | 示例 | 影响 |
|---------|------|------|
| 拼音缩写 | "fjld_type" | 大模型无法理解 |
| 业务编码 | "CRTS_JL01" | 无业务含义 |
| 过于专业 | "T+1日终批处理清算标识" | 大模型理解偏差 |
| 过于简单 | "类型" | 信息量不足 |

**处理策略：**

1. **质量评分**：提取 COMMENT 后自动评分
   - 长度 < 4 字符 → 低质量
   - 纯英文缩写/拼音 → 低质量
   - 包含业务黑话（日终、清算、轧差等）→ 需增强

2. **优先级覆盖**：`schema.yaml` 中的人工描述优先于数据库 COMMENT

3. **AI 增强改写**：对专业术语 COMMENT，用 LLM 改写为通俗描述 + 补充同义词
   ```
   原始 COMMENT: "T+1日终批处理时的清算标识"
   AI 改写: "交易结算状态（日终批量处理）：0-未清算 1-清算中 2-已清算"
   同义词扩展: "清算=结算=到账"
   ```

4. **低质量 COMMENT 标记**：初始化时输出报告，提示哪些字段需要人工补充描述
   ```
   [WARN] 以下字段 COMMENT 质量较低，建议在 schema.yaml 中补充描述：
     - orders.fjld_type: "fjld_type"
     - orders.CRTS_JL01: "CRTS_JL01"
   ```

### 10.2.6 触发时机

| 触发方式 | 时机 | 执行内容 |
|---------|------|---------|
| 数据库就绪后 | 数据库表结构已创建 | 全量提取 → 质量评分 → AI 增强 → 生成报告 |
| DDL 变更检测 | 数据库表结构变更 | 增量检测变更字段 → 质量评分 → 提示更新 |
| 定时任务 | 每天凌晨（可配置） | 全量扫描 → 质量评分 → 输出日报 |
| 人工触发 | 管理后台点击"刷新语义层" | 全量重新提取 → 覆盖更新 |

**首次部署流程：**

```
部署服务
  ↓
人工准备基础 configs/metrics.yaml（核心指标、核心维度描述）
  ↓
数据库表结构就绪
  ↓
执行 init_semantic.py（自动提取表结构，补充无人工描述的字段）
  ↓
查看质量报告，人工补充低质量字段
  ↓
执行 init_vector_store.py（写入向量库）
  ↓
服务可用
```

> **注意：** 业务指标（销售额、GMV）和核心维度描述必须人工在 `metrics.yaml` 中定义，无法从数据库自动提取。自动提取只能补充表结构、字段类型、COMMENT 等基础信息。

## 10.3 枚举值映射

维度配置支持 `value_map`，将业务术语映射到底层存储值：

```yaml
dimensions:
  gender:
    column: gender_code
    description: "性别"
    value_map:
      "男性": 1
      "女性": 2
      "未知": 0
```

**工作流程：**

1. **RAG 注入**：Prompt 中显示 `"gender: 男性(1)、女性(2)、未知(0)"`
2. **LLM 生成 DSL**：`{"field": "gender", "operator": "=", "value": "男性"}`
3. **语义层展开**：`"男性"` → `gender_code = 1`
4. **最终 SQL**：`WHERE gender_code = 1`

## 10.4 枚举值管理（大规模 + 动态更新）

YAML 中的 `value_map` 适合少量静态枚举。实际业务中枚举值数量大且频繁更新，需要独立管理方案。

### 10.4.1 存储方案

| 存储方式 | 适用场景 | 动态更新 |
|---------|---------|---------|
| YAML `value_map` | 少量静态枚举（性别、状态等） | 需重启 |
| 数据库表 `enum_mappings` | 大量枚举、频繁更新 | API 热更新 |
| 数据库字典表同步 | 已有字典表的业务系统 | 定时自动同步 |

推荐数据库表方案：

```sql
CREATE TABLE nl2dsl_enum_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dimension_name TEXT NOT NULL,
    biz_value TEXT NOT NULL,
    db_value TEXT NOT NULL,
    description TEXT,
    frequency INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(dimension_name, biz_value)
);
```

### 10.4.2 加载与热更新

```
系统启动
  ↓
加载 YAML 中的 value_map（基础枚举）
  ↓
加载数据库 enum_mappings 表（动态枚举，覆盖 YAML）
  ↓
写入内存缓存（dict: dimension_name → {biz_value: db_value}）
  ↓
提供热更新 API：POST /api/v1/admin/enums/refresh
```

### 10.4.3 自动同步（从数据库字典表）

同步配置：

```yaml
# configs/enum_sync.yaml
auto_sync:
  - dimension: gender
    source_table: dict_gender
    db_value_column: code
    biz_value_column: label
    sync_interval: 3600  # 秒
```

### 10.4.4 管理接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/admin/enums` | GET | 查询所有枚举映射 |
| `/api/v1/admin/enums` | POST | 新增映射 |
| `/api/v1/admin/enums/{id}` | PUT | 修改映射 |
| `/api/v1/admin/enums/refresh` | POST | 热更新缓存 |

### 10.4.5 优先级规则

```
数据库 enum_mappings 表  >  YAML value_map  >  自动同步字典表
```

### 10.4.6 可选值样本维护

RAG 检索时，Prompt 中需要注入字段的可选值样本。

**样本来源：**

| 来源 | 适用场景 | 提取方式 |
|------|---------|---------|
| 数据库 ENUM 类型 | PostgreSQL 枚举字段 | 解析 ENUM 定义 |
| 字典表/维度表 | 地区表、状态码表等 | 全量读取字典表 |
| DISTINCT 抽样 | 任意字段（无字典表时） | `SELECT DISTINCT field LIMIT 1000` |
| 人工配置 | 核心字段（性别、状态等） | 管理后台维护 |

**敏感字段过滤（不做 DISTINCT）：**

```python
SKIP_DISTINCT_PATTERNS = [
    r'.*phone.*', r'.*id_card.*', r'.*email.*',
    r'.*password.*', r'.*_no$', r'.*_id$'
]
```

**大值域截断：**

```python
if len(values) > 100:
    top_values = get_top_frequent(table, field, limit=50)
    recent_values = get_recent(table, field, limit=10)
    values = top_values + recent_values
```

**Prompt 注入格式：**

```
【字段: region】
说明: 地区编码
可选值: 华东(huadong), 华南(huanan), 华北(huabei), ...
```

## 10.5 指标展开

DSL 中的 `metric: "gmv"` → Semantic Layer 自动展开为 `SUM(pay_amount)`。
