"""Clarification detector for ambiguous user queries.

Detects missing context (time, metric specificity, dimension ambiguity)
and returns clarification questions instead of guessing.
"""

from __future__ import annotations

from nl2dsl.dsl.models import ClarificationItem


_TIME_KEYWORDS = {
    "本月", "上月", "今天", "昨天", "最近", "年", "月", "日", "周",
    "上半年", "下半年", "季度", "Q1", "Q2", "Q3", "Q4",
    "1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月",
    "2023", "2024", "2025",
}

_METRIC_AMBIGUOUS: dict[str, list[str]] = {
    "销量": ["支付订单量", "发货数量", "完成数量"],
    # "销售额" removed — maps clearly to sales_amount in the registry
    "客户数": ["注册用户", "下单用户", "支付用户"],
}

_DIMENSION_AMBIGUOUS: dict[str, list[str]] = {
    "地区": ["收货地址", "发货仓库", "注册地"],
    "时间": ["下单时间", "发货时间", "支付时间"],
}


class ClarificationDetector:
    """Detect ambiguity in user queries before DSL generation."""

    def __init__(self):
        pass

    def detect(self, question: str) -> list[ClarificationItem]:
        """Analyze user question and return list of ambiguities."""
        items: list[ClarificationItem] = []
        question = question.lower()

        # 1. 时间缺失检测 — 只在问题明显涉及时序/变化时才要求时间范围
        # 简单查询如"查询销售额"不需要强制指定时间
        time_sensitive_keywords = {"趋势", "变化", "增长", "下降", "同比", "环比", "最近", "走势", "波动"}
        if any(kw in question for kw in time_sensitive_keywords) and not self._has_time_context(question):
            items.append(
                ClarificationItem(
                    type="time_missing",
                    question="请确认时间范围",
                    options=["本月", "上月", "最近7天", "最近30天", "全部"],
                )
            )

        # 2. 指标歧义检测
        for keyword, options in _METRIC_AMBIGUOUS.items():
            if keyword in question:
                items.append(
                    ClarificationItem(
                        type="metric_ambiguous",
                        question=f'"{keyword}" 的具体含义',
                        options=options,
                    )
                )

        # 3. 维度歧义检测
        for keyword, options in _DIMENSION_AMBIGUOUS.items():
            if keyword in question:
                items.append(
                    ClarificationItem(
                        type="dimension_ambiguous",
                        question=f'"{keyword}" 指',
                        options=options,
                    )
                )

        # 4. 比较基准歧义
        if "增长" in question or "下降" in question or "同比" in question or "环比" in question:
            if not any(kw in question for kw in ("同比", "环比", "上月", "去年")):
                items.append(
                    ClarificationItem(
                        type="comparison_ambiguous",
                        question="对比基准",
                        options=["环比上月", "同比去年", "不对比，只看当前值"],
                    )
                )

        return items

    def _has_time_context(self, question: str) -> bool:
        """Check if question contains explicit time context."""
        for kw in _TIME_KEYWORDS:
            if kw in question:
                return True
        # Also check for date patterns like 2024-01, 2024年
        import re
        if re.search(r"\d{4}[-/年]\d{1,2}", question):
            return True
        return False
