# Rerank 集成方案

## 1. 背景

当前 RAG 检索链路：

```
用户问题 → jieba 分词提取关键词 → 向量检索(top-k) → 按ID去重 → 直接拼prompt
```

**问题**：没有精排环节。召回的 5 条结果中，第 1 条和第 5 条的相关性差异可能很大，但都平等地进入 prompt。导致：
- 不相关记录污染 prompt，LLM 被误导生成错误 DSL
- 术语映射 section 中混入无关术语，LLM 选错 alias
- history 示例召回了语义相近但意图不同的案例

## 2. 目标

在现有混合检索（jieba 关键词 + 向量语义）之后，增加一层 **Cross-Encoder 精排**：

```
用户问题
  → [粗排] 混合检索：每集合召回 top 10
  → [精排] 每集合独立 rerank：CrossEncoder 打分排序
  → [过滤] 丢弃 rerank_score < 0.5 的
  → [兜底] 空召回时回退到原始排序前 3 条
  → [预算] token 长度截断
  → 拼 Prompt
```

## 3. 方案设计

### 3.1 组件设计

```
nl2dsl/rag/
├── base.py            # 已有 — 增加 RerankerBase ABC
├── reranker.py        # 新增 — BGEReranker + MockReranker
├── retriever.py       # 改造 — 集成 rerank 步骤
├── store.py           # 已有 — 不变
├── embedder.py        # 已有 — 不变
└── sync.py            # 已有 — 不变
```

### 3.2 RerankerBase 接口

```python
class RerankerBase(ABC):
    @abstractmethod
    def rerank(self, query: str, candidates: list[str]) -> list[float]:
        """Return relevance score for each candidate text.
        Higher = more relevant. Typical range: 0 ~ 1.
        """
```

### 3.3 BGEReranker 实现

使用 `sentence-transformers.CrossEncoder`：

```python
from sentence_transformers import CrossEncoder

class BGEReranker(RerankerBase):
    def __init__(self, model_path: str, device: str = "cpu"):
        self._model = CrossEncoder(model_path, device=device)

    def rerank(self, query: str, candidates: list[str]) -> list[float]:
        pairs = [(query, c) for c in candidates]
        scores = self._model.predict(pairs)
        return scores.tolist()
```

**模型**：`BAAI/bge-reranker-base`（278M 参数，~420MB），已下载到 `D:/claude_work/model/bge-reranker-base/`。

**为什么不用 API（Cohere/智谱）**：
- 增加延迟（+100-300ms）和 API 成本
- 本地推理更可控，与现有 BGE embedder 同生态

### 3.4 Retriever 改造

#### 构造函数

```python
class RAGRetriever:
    def __init__(self, store, embedder, reranker: RerankerBase | None = None):
        self._store = store
        self._embedder = embedder
        self._reranker = reranker
```

#### retrieve_hybrid 改造

```python
def retrieve_hybrid(self, query, coarse_k=10, fine_n=5):
    # Step 1: 粗排（现有逻辑，每集合召回 coarse_k 条）
    raw = self._coarse_retrieve(query, top_k=coarse_k)

    # Step 2: 精排 — 每集合独立 rerank
    if self._reranker:
        for col in self.COLLECTIONS:
            candidates = raw.get(col, [])
            if not candidates:
                continue

            texts = [c["text"] for c in candidates]
            scores = self._reranker.rerank(query, texts)

            for c, score in zip(candidates, scores):
                c["rerank_score"] = score

            # 按分数降序
            candidates.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)

            # 阈值过滤（< 0.5 丢弃）
            filtered = [c for c in candidates if c.get("rerank_score", 0) >= 0.5]

            # 兜底：过滤后为空，回退到原始排序前 3 条
            if not filtered and candidates:
                filtered = candidates[:3]

            raw[col] = filtered[:fine_n]

    return raw
```

**为什么每集合独立 rerank（而非全局）**：
- schema / metrics / terms / history 的 text 格式语义完全不同
- 全局 rerank 会让 reranker 在"指标定义"和"历史示例"之间做比较，打分尺度不一致
- 独立 rerank 保留集合语义边界，build_context 中每个 section 独立控制数量

#### build_context 改造 — 增加 token 预算

```python
def build_context(self, query, top_k=5, max_chars: int = 4000):
    results = self.retrieve_hybrid(query, coarse_k=10, fine_n=top_k)

    parts = []
    total_chars = 0

    # 优先级：terms > schema > metrics > history
    # terms 是强约束，必须优先保留
    priority = ["terms", "schema", "metrics", "history"]

    for col in priority:
        records = results.get(col, [])
        section_texts = []
        for r in records:
            text = r["text"]
            if total_chars + len(text) > max_chars:
                break
            total_chars += len(text)
            section_texts.append(text)

        if section_texts:
            parts.append(self._format_section(col, section_texts))

    return "\n\n".join(parts)
```

### 3.5 配置项

```python
# config.py
class Settings(BaseSettings):
    # ... 现有配置 ...

    reranker_enabled: bool = True
    reranker_model: str = "D:/claude_work/model/bge-reranker-base"
    reranker_device: str = "cpu"
    reranker_coarse_k: int = 10      # 粗排召回数
    reranker_fine_n: int = 5         # 精排后保留数
    reranker_threshold: float = 0.5  # 过滤阈值
    reranker_max_context_chars: int = 4000
```

### 3.6 Engine 初始化

```python
# engine.py _load_defaults
reranker = None
if settings.reranker_enabled and settings.reranker_model:
    try:
        from nl2dsl.rag.reranker import BGEReranker
        reranker = BGEReranker(
            model_path=settings.reranker_model,
            device=settings.reranker_device,
        )
    except Exception as e:
        logger.warning("Reranker load failed, continuing without: %s", e)

rag_retriever = RAGRetriever(
    store=store,
    embedder=embedder,
    reranker=reranker,
)
```

### 3.7 兼容性

| 场景 | 行为 |
|------|------|
| reranker 未配置 | 保持现有逻辑，零影响 |
| reranker 加载失败 | 降级为无 rerank，记录 warning，继续运行 |
| 单元测试 | 注入 MockReranker，无需加载真实模型 |
| 多域 | 每个域的 RAGRetriever 独立持有 reranker 引用（reranker 实例跨域共享） |

## 4. 测试方案 — 如何量化收益

### 4.1 核心指标

| 指标 | 定义 | 测量方式 |
|------|------|---------|
| **R@5** (Recall@5) | 正确答案是否在召回 top 5 中 | 人工标注 20 条测试 query，检查目标记录是否在召回结果中 |
| **MRR** (Mean Reciprocal Rank) | 正确答案的平均排名倒数 | 对 20 条测试 query，记录目标记录在第几位 |
| **NDCG@5** | 排序质量（高分记录排前面） | 人工给召回结果标注相关性分数（0-3），计算 NDCG |
| **DSL 准确率** | LLM 生成的 DSL 是否正确 | 端到端测试：20 条 query → 看 validate_dsl 是否一次通过 |
| **Latency** | 单次查询延迟增加 | `time.perf_counter()` 测量 rerank 耗时 |

### 4.2 测试数据集

构建 20 条覆盖典型场景的测试 query：

```yaml
test_queries:
  # 简单单指标
  - query: "查询销售额"
    expected_metrics: ["sales_amount"]
    expected_terms: ["sales_amount"]

  # 术语映射（别名 → 指标）
  - query: "各品牌的流水"
    expected_metrics: ["gmv"]
    expected_terms: ["gmv"]  # "流水"是 gmv 的别名

  # 多表 join
  - query: "各客户类型的订单量"
    expected_metrics: ["order_count"]
    expected_dimensions: ["customer_type"]
    expected_joins: ["customer_dim"]

  # 带 filter
  - query: "华东地区的客单价"
    expected_metrics: ["avg_order_value"]
    expected_filters: [{field: "region", value: "华东"}]

  # 模糊/口语化
  - query: "卖得最好的5款货"
    expected_metrics: ["sales_amount"]
    expected_limit: 5

  # 歧义/多意图
  - query: "对比今年和去年华东销售额"
    expected_complexity: "complex"  # 可能触发 decompose

  # 不存在的指标（负例）
  - query: "查询利润率"
    expected_metrics: []  # 未注册，应召回为空或低分
```

### 4.3 A/B 对比测试

```python
def test_rerank_benefit():
    """对比开启/关闭 rerank 的召回质量。"""
    queries = load_test_queries()  # 20 条

    # 无 rerank（当前逻辑）
    retriever_no_rerank = RAGRetriever(store, embedder, reranker=None)
    results_without = [retriever_no_rerank.retrieve_hybrid(q) for q in queries]

    # 有 rerank
    retriever_with = RAGRetriever(store, embedder, reranker=BGEReranker(MODEL_PATH))
    results_with = [retriever_with.retrieve_hybrid(q) for q in queries]

    # 计算指标
    print("=== Recall@5 ===")
    print(f"Without rerank: {recall_at_5(results_without, queries)}")
    print(f"With rerank:    {recall_at_5(results_with, queries)}")

    print("=== MRR ===")
    print(f"Without rerank: {mean_reciprocal_rank(results_without, queries)}")
    print(f"With rerank:    {mean_reciprocal_rank(results_with, queries)}")

    print("=== NDCG@5 ===")
    print(f"Without rerank: {ndcg_at_5(results_without, queries)}")
    print(f"With rerank:    {ndcg_at_5(results_with, queries)}")

    print("=== DSL Accuracy ===")
    print(f"Without rerank: {dsl_accuracy(results_without, queries)}")
    print(f"With rerank:    {dsl_accuracy(results_with, queries)}")
```

### 4.4 端到端 DSL 准确率测试

最直观的收益指标：**rerank 是否让 LLM 生成的 DSL 更准**。

```python
def test_dsl_accuracy():
    """端到端：query → RAG → LLM → DSL → validate。"""
    test_cases = load_test_queries()

    for case in test_cases:
        # 分别用两种 retriever 走完整链路
        dsl_without = generate_dsl(case.query, retriever_no_rerank)
        dsl_with = generate_dsl(case.query, retriever_with)

        # 校验
        valid_without = validator.validate(dsl_without)
        valid_with = validator.validate(dsl_with)

        # 对比 metrics/dimensions/filters 是否与预期一致
        # 记录差异
```

### 4.5 延迟测试

```python
def test_latency():
    """测量 rerank 增加的延迟。"""
    import time

    retriever = RAGRetriever(store, embedder, reranker=BGEReranker(MODEL_PATH))

    times = []
    for _ in range(10):
        start = time.perf_counter()
        retriever.retrieve_hybrid("查询华东销售额", coarse_k=10, fine_n=5)
        times.append(time.perf_counter() - start)

    print(f"Avg latency: {sum(times)/len(times)*1000:.1f}ms")
    print(f"Max latency: {max(times)*1000:.1f}ms")
```

**预期延迟**：
- 当前（无 rerank）：~50-100ms
- 加 rerank（40 对 × 10ms）：~200-400ms

### 4.6 阈值调优实验

测试不同阈值对结果的影响：

```python
for threshold in [0.3, 0.5, 0.7, 0.9]:
    retriever = RAGRetriever(store, embedder, reranker)
    # 临时修改阈值
    results = [retriever.retrieve_hybrid(q, threshold=threshold) for q in queries]
    print(f"Threshold={threshold}: Recall={recall(results)}, Avg_results_per_col={avg_count(results)}")
```

**目标**：找到平衡点——过滤掉噪声，但不过度过滤导致 section 缺失。

## 5. 实施步骤

| 步骤 | 文件 | 内容 | 预估时间 |
|------|------|------|---------|
| 1 | `nl2dsl/rag/base.py` | 增加 `RerankerBase` ABC | 10min |
| 2 | `nl2dsl/rag/reranker.py` | `BGEReranker` + `MockReranker` | 30min |
| 3 | `nl2dsl/rag/retriever.py` | 改造 `retrieve_hybrid` + `build_context` | 1h |
| 4 | `nl2dsl/config.py` | 增加 6 个 reranker 配置项 | 10min |
| 5 | `nl2dsl/engine.py` | 初始化 reranker 并注入 | 20min |
| 6 | `tests/unit/test_rag_reranker.py` | MockReranker 单元测试 | 30min |
| 7 | `tests/benchmark/test_rerank_benefit.py` | A/B 对比测试（R@5, MRR, NDCG） | 1h |
| 8 | `tests/benchmark/test_dsl_accuracy.py` | 端到端 DSL 准确率测试 | 1h |

## 6. 风险与回退

| 风险 | 影响 | 回退方案 |
|------|------|---------|
| reranker 模型加载失败（OOM/路径问题） | RAG 完全不可用 | 捕获异常，降级为 `reranker=None`，保持现有逻辑 |
| rerank 延迟过高（>500ms） | 用户体验差 | 调低 `coarse_k`（10→5），或减少 rerank 对数 |
| 阈值过滤过度 | prompt section 缺失 | 调低阈值（0.5→0.3），或启用兜底回退 |
| 模型输出分数分布异常 | 排序错乱 | 加一层 z-score 归一化，或直接禁用 rerank |

## 7. 决策点

实施前需要确认：

1. **是否接受 +200-400ms 延迟？** 如果查询链路总延迟 500ms（主要是 LLM），增加 200ms 是可接受的。
2. **测试数据集谁来标注？** 需要人工标注 20 条 query 的预期召回结果，用于量化收益。
3. **是否先做 benchmark 再决定是否合入？** 建议先写测试跑数据，看到收益后再合入主线。
