"""Semantic validation for DSL after generation, before SQL building.

Validates: field existence, type consistency, condition conflicts,
having-requires-metric, format correctness.

Returns (errors, warnings) where:
- errors: list[str] -- block execution, trigger auto-correction
- warnings: list[SemanticWarning] -- log only, don't block
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nl2dsl.dsl.models import DSL, Filter, FilterTreeNode, Having, Aggregation


@dataclass
class SemanticWarning:
    category: str
    message: str


class SemanticValidator:
    def __init__(self, registry: dict):
        self._metrics = set(registry.get("metrics", {}).keys())
        self._dimensions = set(registry.get("dimensions", {}).keys())
        self._data_sources = set(registry.get("data_sources", {}).keys())
        self._fields = registry.get("fields", {})

    def validate(self, dsl: DSL) -> tuple[list[str], list[SemanticWarning]]:
        errors: list[str] = []
        warnings: list[SemanticWarning] = []

        self._validate_data_source(dsl, errors)
        self._validate_metrics(dsl, errors)
        self._validate_dimensions(dsl, errors)
        self._validate_filters(dsl, errors, warnings)
        self._validate_having(dsl, errors)
        self._validate_condition_conflicts(dsl, errors)

        return errors, warnings

    def _validate_data_source(self, dsl: DSL, errors: list[str]) -> None:
        if dsl.data_source not in self._data_sources:
            errors.append(f"数据源 '{dsl.data_source}' 不存在")

    def _validate_metrics(self, dsl: DSL, errors: list[str]) -> None:
        if dsl.metrics:
            for m in dsl.metrics:
                if m.alias and m.alias not in self._metrics:
                    errors.append(f"指标 '{m.alias}' 不存在")

    def _validate_dimensions(self, dsl: DSL, errors: list[str]) -> None:
        if dsl.dimensions:
            for d in dsl.dimensions:
                if d not in self._dimensions:
                    errors.append(f"维度 '{d}' 不存在")

    def _validate_filters(
        self, dsl: DSL, errors: list[str], warnings: list[SemanticWarning]
    ) -> None:
        if dsl.filters is None:
            return

        if isinstance(dsl.filters, FilterTreeNode):
            self._validate_filter_tree(dsl.filters, errors, warnings)
        elif isinstance(dsl.filters, list):
            for f in dsl.filters:
                self._validate_filter_leaf(f, errors, warnings)

    def _validate_filter_tree(
        self, node: FilterTreeNode, errors: list[str], warnings: list[SemanticWarning]
    ) -> None:
        for child in node.children:
            if isinstance(child, FilterTreeNode):
                self._validate_filter_tree(child, errors, warnings)
            else:
                self._validate_filter_leaf(child, errors, warnings)

    def _validate_filter_leaf(
        self, f: Filter, errors: list[str], warnings: list[SemanticWarning]
    ) -> None:
        # Field existence check -> warning (not error, unknown fields may be valid)
        if f.field not in self._fields and f.field not in self._dimensions:
            warnings.append(
                SemanticWarning(
                    "unknown_field",
                    f"过滤字段 '{f.field}' 未在语义层注册，请确认拼写正确",
                )
            )

        # Numeric operator type check
        numeric_ops = {">", "<", ">=", "<=", "between"}
        if f.operator in numeric_ops:
            if f.operator == "between":
                if not isinstance(f.value, (list, tuple)) or len(f.value) != 2:
                    errors.append(
                        f"'between' operator requires a [min, max] list, got {f.value!r}"
                    )
            elif not isinstance(f.value, (int, float)):
                errors.append(
                    f"Operator '{f.operator}' requires a numeric value, got "
                    f"{type(f.value).__name__}"
                )

        # 'in' operator format check
        if f.operator == "in" and not isinstance(f.value, list):
            errors.append(
                f"'in' operator requires a list value, got {type(f.value).__name__}"
            )

        # Value domain check -> warning
        field_info = self._fields.get(f.field, {})
        allowed = field_info.get("allowed_values")
        if allowed and f.value is not None and f.value not in allowed:
            if f.operator == "=" or (f.operator == "in" and isinstance(f.value, list)):
                val_to_check = f.value if f.operator == "=" else f.value
                if isinstance(val_to_check, list):
                    unknown = [v for v in val_to_check if v not in allowed]
                    if unknown:
                        warnings.append(
                            SemanticWarning(
                                "value_domain",
                                f"值 {unknown!r} 不在 '{f.field}' 的已知取值中 "
                                f"{allowed!r}",
                            )
                        )
                elif val_to_check not in allowed:
                    warnings.append(
                        SemanticWarning(
                            "value_domain",
                            f"值 '{val_to_check}' 不在 '{f.field}' 的已知取值中 "
                            f"{allowed!r}",
                        )
                    )

    def _validate_having(self, dsl: DSL, errors: list[str]) -> None:
        if not dsl.having:
            return

        if not dsl.metrics:
            errors.append("having 必须与 metrics 同时出现，不能单独使用")
            return

        metric_aliases = {m.alias for m in dsl.metrics if m.alias}
        for h in dsl.having:
            if h.field not in metric_aliases:
                errors.append(
                    f"having 字段 '{h.field}' 不是 metrics 中的 alias: {metric_aliases}"
                )

    def _validate_condition_conflicts(self, dsl: DSL, errors: list[str]) -> None:
        """Detect conflicting conditions like A=1 AND A=2."""
        filters = dsl.filters
        if filters is None:
            return

        # Collect all leaf filters
        leafs: list[Filter] = []
        if isinstance(filters, FilterTreeNode):
            self._collect_leafs(filters, leafs)
        elif isinstance(filters, list):
            leafs = filters

        # Group by field+operator and check for conflicts on '='
        eq_conditions: dict[str, list[Any]] = {}
        for f in leafs:
            if f.operator == "=":
                eq_conditions.setdefault(f.field, []).append(f.value)

        for field, values in eq_conditions.items():
            if len(values) > 1 and len(set(str(v) for v in values)) > 1:
                errors.append(
                    f"conflict: '{field}' has multiple different values {values!r}"
                )

    def _collect_leafs(self, node: FilterTreeNode, out: list[Filter]) -> None:
        for child in node.children:
            if isinstance(child, FilterTreeNode):
                self._collect_leafs(child, out)
            else:
                out.append(child)
