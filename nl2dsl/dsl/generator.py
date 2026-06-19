"""DSL Generator abstraction and retry chain.

Provides:
- DSLGenerator: abstract base for all DSL generation strategies
- RuleBasedDSLGenerator: keyword-based mock generator (for tests/fallback)
- RetryChain: wraps any generator with error feedback + retry logic
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Callable

from nl2dsl.dsl.models import DSL, Aggregation, Filter, OrderBy, PostProcess
from nl2dsl.exceptions import ValidationError
from nl2dsl.query.time_resolver import resolve_time


# Negation cues that, when preceding a value, flip an equality to `!=`.
_NEGATION_CUES = ("非", "不是", "排除", "除外", "不包含", "不含")


def _is_negated(question: str, keyword: str) -> bool:
    """True if ``keyword`` is preceded (within 4 chars) by a negation cue."""
    idx = question.find(keyword)
    while idx != -1:
        prefix = question[max(0, idx - 4):idx]
        if any(cue in prefix for cue in _NEGATION_CUES):
            return True
        idx = question.find(keyword, idx + 1)
    return False


class DSLGenerator(ABC):
    """Abstract base for DSL generation strategies."""

    @abstractmethod
    def generate(self, question: str, data_source: str | None = None) -> DSL:
        """Generate DSL from natural language question."""
        ...


class RuleBasedDSLGenerator(DSLGenerator):
    """Keyword-based DSL generator (mock/fallback implementation).

    Uses hardcoded keyword matching for metrics, dimensions, filters.
    Suitable for testing environments without LLM.
    """

    def __init__(self, registry: dict | None = None):
        self._registry = registry or {}

    def generate(self, question: str, data_source: str | None = None) -> DSL:
        ds = data_source or "orders"
        metrics = []
        dimensions = []
        filters = []
        order_by = []
        limit = 10

        q = question.lower()

        # Metrics
        if any(kw in question for kw in ["销售额", "sales", "业绩", "营收"]):
            metrics.append(Aggregation(func="sum", field="order_amount", alias="sales_amount"))
        elif any(kw in q for kw in ["gmv", "成交总额", "交易额"]):
            metrics.append(Aggregation(func="sum", field="order_amount", alias="gmv"))
        elif any(kw in question for kw in ["订单量", "订单数", "单量", "order count"]):
            metrics.append(Aggregation(func="count", field="id", alias="order_count"))
        elif any(kw in q for kw in ["客单价", "平均订单", "平均消费", "笔单价"]):
            metrics.append(Aggregation(func="avg", field="pay_amount", alias="avg_order_value"))
        elif any(kw in q for kw in ["优惠", "折扣", "让利"]):
            metrics.append(Aggregation(func="sum", field="discount_amount", alias="total_discount"))
        elif any(kw in q for kw in ["销量", "销售数量", "售出数量"]):
            metrics.append(Aggregation(func="sum", field="quantity", alias="total_quantity"))
        else:
            metrics.append(Aggregation(func="sum", field="order_amount", alias="sales_amount"))

        # Dimensions
        if "产品" in question or "product" in q:
            dimensions.append("product_name")
        if "品类" in question or "category" in q:
            dimensions.append("category")
        if "品牌" in question or "brand" in q:
            dimensions.append("brand")
        if "地区" in question or "区域" in question or "region" in q:
            dimensions.append("region")
        if "渠道" in question or "channel" in q or "销售方式" in question:
            dimensions.append("channel")
        if "客户" in question or "customer" in q or "用户" in q or "买家" in question:
            if "客户名" in question or "customer_name" in q or "名称" in question:
                dimensions.append("customer_name")
            else:
                dimensions.append("customer_type")
        if "时间" in question or "日期" in question or "date" in q:
            dimensions.append("order_date")

        if not dimensions:
            dimensions.append("product_name")

        # Helpers for value_map lookup
        dims_registry = self._registry.get("dimensions", {})

        def _map_value(dim_name: str, semantic_value: str) -> str:
            """Map semantic value to DB code via registry value_map."""
            vm = dims_registry.get(dim_name, {}).get("value_map", {})
            return vm.get(semantic_value, semantic_value)

        # Filters
        def _eq_or_ne(field: str, value: str, dim_name: str | None = None) -> Filter:
            """Emit `=` or `!=` based on whether the value is negated in the question."""
            mapped = _map_value(dim_name or field, value) if dim_name else value
            op = "!=" if _is_negated(question, value) else "="
            return Filter(field=field, operator=op, value=mapped)

        if "华东" in question:
            filters.append(_eq_or_ne("region", "华东", "region"))
        if "华南" in question:
            filters.append(_eq_or_ne("region", "华南", "region"))
        if "华北" in question:
            filters.append(_eq_or_ne("region", "华北", "region"))
        if "西南" in question:
            filters.append(_eq_or_ne("region", "西南", "region"))
        if "线上" in question:
            filters.append(_eq_or_ne("channel", "线上", "channel"))
        if "线下" in question:
            filters.append(_eq_or_ne("channel", "线下", "channel"))
        if "分销" in question:
            filters.append(_eq_or_ne("channel", "分销", "channel"))
        for cat in ("手机", "电脑", "家电", "服饰"):
            if cat in question:
                filters.append(_eq_or_ne("category", cat))
        if "新客" in question:
            filters.append(_eq_or_ne("customer_type", "新客"))
        if "老客" in question:
            filters.append(_eq_or_ne("customer_type", "老客"))
        if "VIP" in question:
            filters.append(_eq_or_ne("customer_type", "VIP"))

        # Numeric / range / comparison filters on price (Week 2 semantics).
        self._add_numeric_filters(filters, question)

        # Time expression resolution (Week 3): resolve any relative/absolute
        # time expression in the question into DSL.time_field/time_range.
        time_field = self._resolve_time_field(ds)
        time_range = None
        if time_field:
            resolved = resolve_time(question, time_field)
            if resolved is not None:
                time_range = resolved.time_range

        # Order by
        if metrics:
            order_by.append(OrderBy(field=metrics[0].alias or metrics[0].field, direction="desc"))

        # Limit
        if "top" in q or "最高" in question or "最多" in question:
            limit = 10
        elif "全部" in question or "所有" in question:
            limit = 100

        post_process = self._build_post_process(
            question=question,
            metrics=metrics,
            dimensions=dimensions,
        )
        if post_process is not None:
            # The SQL layer must return the complete grouped result; the
            # governed post-processor applies the per-group limit afterwards.
            limit = None

        return DSL(
            metrics=metrics,
            dimensions=dimensions,
            filters=filters or None,
            order_by=order_by or None,
            limit=limit,
            data_source=ds,
            time_field=time_field if time_range else None,
            time_range=time_range,
            post_process=post_process,
        )

    def _resolve_time_field(self, data_source: str) -> str | None:
        """Find the date-typed time dimension for a data source.

        Returns the first dimension declared under ``data_source`` whose
        ``type == "date"`` (e.g. ``order_date`` for ``orders``), falling back
        to a scan of all registry dimensions. Mirrors
        ``SemanticConfig.get_time_field`` but works off the raw registry dict
        available to the rule-based generator.
        """
        dims_registry = self._registry.get("dimensions", {})
        sources = self._registry.get("data_sources", {})
        for dim_id in sources.get(data_source, {}).get("dimensions", []):
            if dims_registry.get(dim_id, {}).get("type") == "date":
                return dim_id
        for dim_id, cfg in dims_registry.items():
            if isinstance(cfg, dict) and cfg.get("type") == "date":
                return dim_id
        return None

    @staticmethod
    def _build_post_process(
        question: str,
        metrics: list[Aggregation],
        dimensions: list[str],
    ) -> PostProcess | None:
        if not metrics:
            return None
        metric = metrics[0].alias or metrics[0].field

        if any(keyword in question for keyword in ("占比", "比例", "贡献度")):
            return PostProcess(
                type="proportion",
                metric=metric,
                output_field=f"{metric}_proportion",
            )

        grouped_rank = (
            len(dimensions) >= 2
            and any(marker in question for marker in ("各", "每个", "每种"))
            and any(marker in question for marker in ("最高", "最低", "前", "后"))
        )
        if grouped_rank:
            match = re.search(r"(?:前|最高的?|最低的?|后)\s*(\d+)", question)
            top_n = int(match.group(1)) if match else 1
            direction = "asc" if any(k in question for k in ("最低", "最少", "后")) else "desc"
            group_candidates = (
                ("品类", "category"),
                ("地区", "region"),
                ("区域", "region"),
                ("渠道", "channel"),
                ("品牌", "brand"),
                ("客户", "customer_type"),
            )
            group_dimension = next(
                (
                    dim
                    for keyword, dim in group_candidates
                    if any(
                        marker in question
                        for marker in (
                            f"各{keyword}",
                            f"每个{keyword}",
                            f"每种{keyword}",
                        )
                    )
                    and dim in dimensions
                ),
                dimensions[0],
            )
            return PostProcess(
                type="group_top_n",
                metric=metric,
                group_by=[group_dimension],
                top_n=top_n,
                direction=direction,
            )
        return None

    @staticmethod
    def _add_numeric_filters(filters: list, question: str) -> None:
        """Detect numeric comparison / range / negation on price.

        Supports:
        - range: "价格在5000到20000之间" / "介于5000和20000之间" → between [5000, 20000]
        - comparison: "价格大于5000"/"超过5000"/">=8000"/"小于3000" → > / >= / <
        Comparison is skipped when a range was matched (range takes precedence).
        """
        # Range: between X and Y  (X到Y之间 / 介于X和Y之间)
        range_match = re.search(
            r"(?:价格|单价)?[在介]?于?\s*(\d+(?:\.\d+)?)\s*(?:到|和|至|-|~)\s*(\d+(?:\.\d+)?)\s*(?:元)?之间",
            question,
        )
        if range_match:
            lo, hi = float(range_match.group(1)), float(range_match.group(2))
            lo, hi = (lo, hi) if lo <= hi else (hi, lo)
            filters.append(Filter(field="price", operator="between", value=[lo, hi]))
            return

        # Comparison: look for an explicit number near a comparison cue.
        comp_match = re.search(
            r"价格(?:大于等于|大于|超过|高于|不少于|不低于|小于等于|小于|低于|不多于|不高于|≥|<=|>=|>|<)\s*(\d+(?:\.\d+)?)"
            r"|大于等于\s*(\d+(?:\.\d+)?)|大于\s*(\d+(?:\.\d+)?)|超过\s*(\d+(?:\.\d+)?)"
            r"|小于等于\s*(\d+(?:\.\d+)?)|小于\s*(\d+(?:\.\d+)?)",
            question,
        )
        if not comp_match:
            return

        # Determine operator + value from whichever group matched.
        token = comp_match.group(0)
        value = float(next(g for g in comp_match.groups() if g is not None))
        if any(c in token for c in ("大于等于", "不少于", "不低于", "≥", ">=")):
            op = ">="
        elif any(c in token for c in ("小于等于", "不多于", "不高于", "<=")):
            op = "<="
        elif any(c in token for c in ("大于", "超过", "高于", ">")):
            op = ">"
        elif any(c in token for c in ("小于", "低于", "<")):
            op = "<"
        else:
            return
        filters.append(Filter(field="price", operator=op, value=value))


class MaxRetryExceeded(Exception):
    """Raised when all retry attempts are exhausted."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"DSL generation failed after retries. Errors: {'; '.join(errors)}")


class RetryChain(DSLGenerator):
    """Wraps a DSL generator with error feedback + retry logic.

    On failure, captures the error, feeds it back to the generator,
    and retries up to max_retries times.
    """

    def __init__(
        self,
        generator: DSLGenerator,
        validator: Callable[[DSL], None] | None = None,
        max_retries: int = 3,
    ):
        self._generator = generator
        self._validator = validator
        self._max_retries = max_retries
        self._errors: list[str] = []

    def generate(self, question: str, data_source: str | None = None) -> DSL:
        """Generate DSL with retry on validation failures."""
        self._errors = []

        for attempt in range(self._max_retries):
            try:
                # Build prompt with error feedback for subsequent attempts
                prompt = self._build_prompt(question)
                dsl = self._generator.generate(prompt, data_source)

                # Validate if validator provided
                if self._validator:
                    self._validator(dsl)

                return dsl

            except (ValidationError, ValueError, KeyError) as e:
                error_msg = str(e)
                self._errors.append(error_msg)
                if attempt < self._max_retries - 1:
                    continue
                raise MaxRetryExceeded(self._errors)

        # Should not reach here, but just in case
        raise MaxRetryExceeded(self._errors)

    def _build_prompt(self, question: str) -> str:
        """Build prompt with error feedback from previous attempts."""
        if not self._errors:
            return question

        feedback = "\n".join(
            f"Attempt {i + 1} failed: {err}" for i, err in enumerate(self._errors)
        )
        return (
            f"{question}\n\n"
            f"Previous attempts failed:\n{feedback}\n\n"
            f"Please fix the errors and generate a correct DSL."
        )
