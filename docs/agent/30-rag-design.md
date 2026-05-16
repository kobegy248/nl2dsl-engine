# 30. RAG 设计

## 30.1 检索内容

| 内容类型 | 来源 | 用途 |
|---------|------|------|
| 表结构信息 | 数据库元数据 + schema.yaml | LLM 了解可用表和字段 |
| 指标定义 | metrics.yaml | LLM 了解业务指标计算方式 |
| 历史查询 | 审计日志表 | Few-shot 示例 |
| 业务术语 | 术语表 | "销售额" → `sales_amount` |
| 错误修正 | feedback 表 | 避免重复错误 |

## 30.2 向量库文本内容构建

向量库存储的不是原始字段名，而是**可嵌入的文本描述**。用户查询通过语义相似度匹配这些描述。

**文本内容包含：**

| 信息来源 | 内容 | 示例 |
|---------|------|------|
| 字段名 | 原始列名 | `order_amount` |
| 注释（COMMENT） | 数据库字段注释 | "订单金额，单位分" |
| 语义层描述 | `metrics.yaml` / `schema.yaml` | "销售额 = SUM(order_amount)" |
| 枚举值 | `value_map` | "性别: 男性(1)、女性(2)" |

**文本组装格式：**

```
表: orders
字段: order_amount
说明: 订单金额，单位分
指标: sales_amount (SUM(order_amount))
```

**注释缺失处理：**

| 情况 | 处理方式 |
|------|---------|
| 有 COMMENT | 直接使用数据库注释 |
| 无 COMMENT，语义层有描述 | 使用 `metrics.yaml` / `schema.yaml` 中的描述 |
| 两者都无 | 自动生成描述（字段名驼峰拆分 + 类型推断） |

## 30.3 技术实现

- **向量库**: Milvus Lite（本地 SQLite 文件），预留 Milvus Server 切换接口
- **嵌入模型**: `sentence-transformers/all-MiniLM-L6-v2` (384维)
- **检索策略**: 余弦相似度，Top-5 召回
- **存储方式**: 本地 `.db` 文件（默认 `./milvus_lite.db`），无需 Docker

## 30.4 向量存储结构

按内容类型分集合存储，每个集合独立检索。

**集合（Collection）设计：**

| 集合名 | 存储内容 | 用途 |
|--------|---------|------|
| `schema` | 表结构、字段描述 | 用户问题 → 匹配相关表和字段 |
| `metrics` | 指标定义 | 用户问题 → 匹配相关指标 |
| `history` | 历史查询（问题 + DSL） | Few-shot 示例 |
| `terms` | 业务术语映射 | 同义词、歧义消解 |
| `feedback` | 错误修正记录 | 避免重复错误 |

**单条记录结构：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | VARCHAR | 唯一标识，如 `table_orders` |
| `vector` | FLOAT_VECTOR(384) | 文本嵌入向量 |
| `text` | VARCHAR | 原始文本（用于检索后展示） |
| `type` | VARCHAR | 记录类型：`table` / `column` / `metric` |
| `source` | VARCHAR | 来源：`database` / `yaml` / `manual` |
| `name` | VARCHAR | 名称，如 `orders` |

**检索策略：**

用户问题同时向多个集合发起检索，合并结果后按相似度排序，取 Top-10 注入 Prompt。

```
用户问题: "上个月销售额"
  ├─ 检索 schema 集合 → 召回 order_amount、sales_amount 相关记录
  ├─ 检索 metrics 集合 → 召回 sales_amount 指标定义
  ├─ 检索 history 集合 → 召回相似历史查询（作为 Few-shot）
  └─ 检索 terms 集合 → 召回 "销售额" 的术语映射
```

## 30.5 检索优化（解决语义鸿沟）

纯向量检索无法理解业务同义词（如"业绩"≠"销售额"），需要多层优化。

### P0: 术语表映射（最核心）

维护业务术语到标准指标名的映射：

```yaml
# configs/terms.yaml
terms:
  sales_amount:
    aliases: ["销售额", "业绩", "销售收入", "营收", "营业额"]
    metric: sales_amount
    description: "含税销售额，不含退款"
```

Prompt 注入时展开别名：
```
【指标】
sales_amount (销售额/业绩/销售收入/营收)
计算方式: SUM(order_amount)
```

### P1: 同义词扩展写入向量库

向量库中每条记录包含所有别名：

| id | text | type |
|----|------|------|
| `metric_sales` | `指标: 销售额(业绩/销售收入/营收), 计算: SUM(order_amount)` | `metric` |

### P2: 混合检索（向量 + 关键词）

```python
# 1. 向量检索 Top-20
vector_results = vector_search(query, top_k=20)

# 2. 关键词补充：检查术语表别名匹配
keyword_results = []
for term, data in terms.items():
    if any(alias in query for alias in data.aliases):
        keyword_results.append(term)

# 3. 合并去重
final_results = deduplicate(vector_results + keyword_results)
```

### P3: 重排序模型

对召回结果用 Cross-Encoder 精排：

```python
from sentence_transformers import CrossEncoder
reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

pairs = [(query, doc.text) for doc in candidates]
scores = reranker.predict(pairs)
# 按 score 排序，取 Top-5
```

## 30.6 Prompt 组装

RAG 检索到的上下文注入到 LLM System Prompt：

```
【表结构】
{retrieved_schema}

【指标定义】
{retrieved_metrics}

【历史查询示例】
{retrieved_examples}

【业务术语】
{retrieved_terms}
```
