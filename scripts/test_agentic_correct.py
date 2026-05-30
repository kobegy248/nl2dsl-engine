"""测试 agentic correct_dsl_node 的工作流。

构造场景：LLM 第一次输出错误指标 → validate 失败 → correct_dsl 触发
→ Step 1: LLM 决定检索关键词 → Step 2: RAG 检索补充上下文 →
Step 3: LLM 拿到补充上下文重新生成正确 DSL → validate 通过。
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from nl2dsl.graph.nodes import _make_correct_dsl_node


class FakeLLM:
    """模拟两阶段 LLM：第一次回 retrieval keyword，第二次回正确 DSL。"""

    def __init__(self):
        self.calls = []

    def generate(self, user_prompt: str, system_prompt: str) -> str:
        self.calls.append({"user": user_prompt[:200], "system": system_prompt[:100]})
        # decide step（系统 prompt 提到"关键词提取助手"）
        if "关键词提取助手" in system_prompt:
            return "ghost_metric"
        # regenerate step（user prompt 应包含失败原因和补充上下文）
        assert "补充的业务知识" in user_prompt, "regenerate prompt 必须含补充上下文"
        # 返回一个正确的 DSL
        return """```json
{"metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
 "dimensions": ["region"],
 "filters": [],
 "limit": 10,
 "data_source": "orders"}
```"""


class FakeRetriever:
    """模拟 RAG，记录被检索了什么。"""

    def __init__(self):
        self.queries = []

    def build_context(self, query: str, top_k: int = 5) -> str:
        self.queries.append(query)
        return f"【模拟 RAG 上下文】检索 '{query}' 找到: sales_amount, region"


def main():
    llm = FakeLLM()
    retriever = FakeRetriever()
    correct_node = _make_correct_dsl_node(
        llm, retriever, {}, llm_system_prompt="test-system-prompt"
    )

    # 构造一个"上一次失败"的 state
    from nl2dsl.dsl.models import DSL, Aggregation
    prev_dsl = DSL(
        metrics=[Aggregation(func="sum", field="order_amount", alias="ghost_metric")],
        dimensions=["region"],
        limit=10,
        data_source="orders",
    )

    state = {
        "question": "查询各地区销售额",
        "data_source": "orders",
        "error": "指标 'ghost_metric' 不存在",
        "error_code": "VALIDATION_ERROR",
        "dsl": prev_dsl,
    }

    result = correct_node(state)

    print("=" * 60)
    print("Agentic correct_dsl 工作流验证")
    print("=" * 60)
    print(f"\n[LLM 调用次数] {len(llm.calls)} (期望: 2)")
    print(f"  - 第1次: 关键词决策 (system=关键词提取助手)")
    print(f"  - 第2次: 修正生成 (含补充上下文)")

    print(f"\n[RAG 检索调用] {len(retriever.queries)} (期望: 1)")
    print(f"  检索关键词: {retriever.queries}")

    print(f"\n[最终 DSL] {result.get('dsl').model_dump() if result.get('dsl') else None}")
    print(f"[status] {result.get('status')} (应为 pending，让 validate 重判)")
    print(f"[error] {result.get('error')} (应为 None，已清错误状态)")

    attempt = result.get("dsl_attempts", {})
    print(f"\n[dsl_attempts]")
    print(f"  source: {attempt.get('source')}")
    print(f"  retrieval_query: {attempt.get('retrieval_query')}")
    print(f"  error_feedback: {attempt.get('error_feedback')}")

    # 断言
    assert len(llm.calls) == 2, f"LLM 应调用 2 次, 实际 {len(llm.calls)}"
    assert len(retriever.queries) == 1, "RAG 应调用 1 次"
    assert retriever.queries[0] == "ghost_metric", f"检索关键词应为 ghost_metric, 实际 {retriever.queries[0]}"
    assert result.get("status") == "pending", "应清空错误状态"
    assert result.get("error") is None, "应清空 error"
    assert result["dsl"].metrics[0].alias == "sales_amount", "修正后应改为 sales_amount"
    assert attempt["source"] == "llm_corrected_agentic", "应标记为 agentic 修正"

    print("\n" + "=" * 60)
    print("✅ 所有断言通过")
    print("=" * 60)


if __name__ == "__main__":
    main()
