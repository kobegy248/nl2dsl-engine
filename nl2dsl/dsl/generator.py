"""DSL Generator abstraction and retry chain.

Provides:
- DSLGenerator: abstract base for all DSL generation strategies
- RuleBasedDSLGenerator: keyword-based mock generator (for tests/fallback)
- RetryChain: wraps any generator with error feedback + retry logic
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from nl2dsl.dsl.models import DSL, Aggregation, Filter, OrderBy
from nl2dsl.exceptions import ValidationError


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
        if "华东" in question:
            filters.append(Filter(field="region", operator="=", value=_map_value("region", "华东")))
        if "华南" in question:
            filters.append(Filter(field="region", operator="=", value=_map_value("region", "华南")))
        if "华北" in question:
            filters.append(Filter(field="region", operator="=", value=_map_value("region", "华北")))
        if "西南" in question:
            filters.append(Filter(field="region", operator="=", value=_map_value("region", "西南")))
        if "线上" in question:
            filters.append(Filter(field="channel", operator="=", value=_map_value("channel", "线上")))
        if "线下" in question:
            filters.append(Filter(field="channel", operator="=", value=_map_value("channel", "线下")))
        if "分销" in question:
            filters.append(Filter(field="channel", operator="=", value=_map_value("channel", "分销")))
        if "手机" in question:
            filters.append(Filter(field="category", operator="=", value="手机"))
        if "电脑" in question:
            filters.append(Filter(field="category", operator="=", value="电脑"))
        if "家电" in question:
            filters.append(Filter(field="category", operator="=", value="家电"))
        if "服饰" in question:
            filters.append(Filter(field="category", operator="=", value="服饰"))
        if "新客" in question:
            filters.append(Filter(field="customer_type", operator="=", value="新客"))
        if "老客" in question:
            filters.append(Filter(field="customer_type", operator="=", value="老客"))
        if "VIP" in question:
            filters.append(Filter(field="customer_type", operator="=", value="VIP"))

        # Order by
        if metrics:
            order_by.append(OrderBy(field=metrics[0].alias or metrics[0].field, direction="desc"))

        # Limit
        if "top" in q or "最高" in question or "最多" in question:
            limit = 10
        elif "全部" in question or "所有" in question:
            limit = 100

        return DSL(
            metrics=metrics,
            dimensions=dimensions,
            filters=filters or None,
            order_by=order_by or None,
            limit=limit,
            data_source=ds,
        )


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
