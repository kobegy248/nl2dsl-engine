"""测试 decompose 节点 + verify_dsl 节点 的工作流。

不依赖真实 LLM/RAG，用 FakeLLM 验证：
1. decompose: 简单问题 KEEP，复杂问题 REWRITE，无法处理的 SPLIT
2. verify_dsl: PASS / WARN / FAIL 输出解析
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from nl2dsl.dsl.models import DSL, Aggregation
from nl2dsl.graph.nodes import (
    _make_decompose_node,
    _make_verify_dsl_node,
    _looks_complex,
)


class FakeLLM:
    """模拟 LLM，按 system_prompt 关键字决定返回内容。"""

    def __init__(self, responses_by_system: dict[str, str]):
        self.responses = responses_by_system
        self.calls = []

    def generate(self, user_prompt: str, system_prompt: str) -> str:
        self.calls.append((system_prompt[:30], user_prompt[:80]))
        for key, resp in self.responses.items():
            if key in system_prompt:
                return resp
        return ""


# ---------- decompose ----------

def test_decompose_simple_skip():
    """没启用 LLM 时直接 skip。"""
    node = _make_decompose_node(llm_client=None)
    state = {"question": "对比今年和去年华东销售额"}
    result = node(state)
    assert result["complexity"] == "simple", "无 LLM 应 skip"
    assert "trace" in result
    print("  [PASS] no-LLM skip")


def test_decompose_simple_question_skipped():
    """问题不含复杂信号词，跳过 LLM 调用。"""
    llm = FakeLLM({"改写助手": "KEEP"})
    node = _make_decompose_node(llm)
    state = {"question": "查询华东销售额"}
    result = node(state)
    assert result["complexity"] == "simple"
    assert len(llm.calls) == 0, "简单问题不该触发 LLM"
    print("  [PASS] simple question skipped (no LLM call)")


def test_decompose_rewrite():
    """LLM 输出 REWRITE，应替换 question 并保留原始。"""
    llm = FakeLLM({"改写助手": "REWRITE\n按年度分组统计华东地区销售额（限定 2023 和 2024 年）"})
    node = _make_decompose_node(llm)
    state = {"question": "对比今年和去年华东销售额"}
    result = node(state)
    assert result["complexity"] == "complex_rewritten"
    assert result["original_question"] == "对比今年和去年华东销售额"
    assert "按年度分组" in result["question"]
    assert len(llm.calls) == 1
    print(f"  [PASS] rewrite: '{state['question']}' -> '{result['question']}'")


def test_decompose_keep():
    """LLM 看完判定 KEEP，不改写。"""
    llm = FakeLLM({"改写助手": "KEEP"})
    node = _make_decompose_node(llm)
    state = {"question": "对比 VIP 和普通客户的销售额"}
    result = node(state)
    assert result["complexity"] == "simple"
    assert "question" not in result, "KEEP 不应改写 question"
    print("  [PASS] keep verdict respected")


def test_decompose_split():
    """LLM 判定 SPLIT（系统暂不支持 fan-out），降级处理。"""
    llm = FakeLLM({"改写助手": "SPLIT"})
    node = _make_decompose_node(llm)
    state = {"question": "对比 VIP 客户的客单价和普通客户的订单量"}
    result = node(state)
    assert result["complexity"] == "complex"
    assert result["rewrite_reason"] is not None
    print("  [PASS] split graceful fallback")


# ---------- verify_dsl ----------

def test_verify_pass():
    """LLM 判 PASS。"""
    llm = FakeLLM({"质量检查员": "PASS"})
    node = _make_verify_dsl_node(llm)
    state = {
        "question": "查询华东地区销售额",
        "dsl": DSL(
            metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
            dimensions=["region"],
            filters=None,
            data_source="orders",
            limit=10,
        ),
        "data": [{"region": "华东", "sales_amount": 12345}],
    }
    result = node(state)
    assert result["verify_status"] == "pass"
    print("  [PASS] verify PASS recognized")


def test_verify_warn_with_reason():
    """LLM 判 WARN 并给出理由。"""
    llm = FakeLLM({"质量检查员": "WARN\n缺少华东过滤"})
    node = _make_verify_dsl_node(llm)
    state = {
        "question": "查询华东地区销售额",
        "dsl": DSL(
            metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
            dimensions=["region"],
            data_source="orders",
            limit=10,
        ),
        "data": [{"region": "华东"}, {"region": "华南"}, {"region": "华北"}],
    }
    result = node(state)
    assert result["verify_status"] == "warn"
    assert result["verify_reason"] == "缺少华东过滤"
    print(f"  [PASS] verify WARN: {result['verify_reason']}")


def test_verify_fail():
    """LLM 判 FAIL。"""
    llm = FakeLLM({"质量检查员": "FAIL\n指标不匹配"})
    node = _make_verify_dsl_node(llm)
    state = {
        "question": "客户数量",
        "dsl": DSL(
            metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
            dimensions=["product_name"],
            data_source="orders",
            limit=10,
        ),
        "data": [],
    }
    result = node(state)
    assert result["verify_status"] == "fail"
    assert "指标不匹配" in result["verify_reason"]
    print(f"  [PASS] verify FAIL: {result['verify_reason']}")


def test_verify_uses_original_question():
    """有 original_question 时优先用它，而不是改写后的。"""
    llm = FakeLLM({"质量检查员": "PASS"})
    node = _make_verify_dsl_node(llm)
    state = {
        "question": "按年度分组统计华东地区销售额（限定 2023 和 2024 年）",  # 改写后
        "original_question": "对比今年和去年华东销售额",  # 原始
        "dsl": DSL(
            metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
            dimensions=["region", "order_date"],
            data_source="orders",
            limit=10,
        ),
        "data": [],
    }
    result = node(state)
    assert result["verify_status"] == "pass"
    # 检查 prompt 中确实出现了原始问题
    sent_user_prompt = llm.calls[0][1]
    assert "对比" in sent_user_prompt or "今年" in sent_user_prompt, \
        f"verify 应使用 original_question, 实际 prompt: {sent_user_prompt}"
    print("  [PASS] verify uses original_question over rewritten")


def test_verify_no_llm_skipped():
    llm = None
    node = _make_verify_dsl_node(llm)
    state = {"question": "x", "dsl": DSL(data_source="orders"), "data": []}
    result = node(state)
    assert result["verify_status"] == "skipped"
    print("  [PASS] verify skipped without LLM")


# ---------- complex pattern detection ----------

def test_looks_complex_detection():
    cases = [
        ("查询华东销售额", False),
        ("对比今年和去年华东销售额", True),
        ("各品牌销售额同比", True),
        ("订单量趋势", True),
        ("最贵的 5 个产品", False),
    ]
    for q, expected in cases:
        got = _looks_complex(q)
        assert got == expected, f"{q!r}: expected {expected}, got {got}"
    print(f"  [PASS] _looks_complex: {len(cases)} cases all correct")


def main():
    print("\n" + "=" * 60)
    print("decompose_node tests")
    print("=" * 60)
    test_decompose_simple_skip()
    test_decompose_simple_question_skipped()
    test_decompose_rewrite()
    test_decompose_keep()
    test_decompose_split()

    print("\n" + "=" * 60)
    print("verify_dsl_node tests")
    print("=" * 60)
    test_verify_pass()
    test_verify_warn_with_reason()
    test_verify_fail()
    test_verify_uses_original_question()
    test_verify_no_llm_skipped()

    print("\n" + "=" * 60)
    print("complex-pattern detection")
    print("=" * 60)
    test_looks_complex_detection()

    print("\n" + "=" * 60)
    print("ALL PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
