"""Filter rules: F001 (Invalid Enum), F002 (Operator-Type Mismatch), F003-F005."""

from nl2dsl.optimizer.base import BaseRule, RuleResult
from nl2dsl.optimizer.metadata import RuleMetadata
from nl2dsl.optimizer.registry import RuleRegistry


# Operators incompatible with numeric fields
NUMERIC_INCOMPATIBLE_OPS = {"like", "ilike"}
# Operators incompatible with boolean fields
BOOLEAN_INCOMPATIBLE_OPS = {">", "<", ">=", "<=", "between", "like", "ilike"}
# Operators incompatible with string fields
STRING_INCOMPATIBLE_OPS = {">", "<", ">=", "<=", "between"}


def _get_field_type(dimension_name: str, context) -> str:
    """Determine the type of a filter field from semantic config."""
    return context.semantic_config.get_dimension_type(dimension_name)


def _find_replacement_op(operator: str, field_type: str) -> str | None:
    """Find a compatible replacement operator."""
    op_lower = operator.lower()
    if field_type in ("integer", "float", "numeric", "number"):
        if op_lower in NUMERIC_INCOMPATIBLE_OPS:
            return "="
    if field_type in ("boolean", "bool"):
        if op_lower in BOOLEAN_INCOMPATIBLE_OPS:
            return "="
    if field_type in ("string", "text", "varchar"):
        if op_lower in STRING_INCOMPATIBLE_OPS:
            return "like"
    return None


@RuleRegistry.register
class F002_OperatorTypeMismatch(BaseRule):
    """Check if filter operator is incompatible with the field's data type."""

    metadata = RuleMetadata(
        error_code="F002",
        category="Filter",
        description="Filter operator is incompatible with field type",
        priority=2,
        severity="Fix",
        confidence="high",
        auto_fixable=True,
    )

    def check(self, dsl: dict, context) -> RuleResult:
        filters = dsl.get("filters") or []
        if not filters:
            return RuleResult.no_issue("F002", "Filter")

        for i, f in enumerate(filters):
            if not isinstance(f, dict):
                continue
            field = f.get("field", "")
            operator = f.get("operator", "=")
            field_type = _get_field_type(field, context)

            # Skip fields not present in the semantic config (defaults to 'string')
            if not context.semantic_config.has_dimension(field):
                continue

            replacement = _find_replacement_op(operator, field_type)
            if replacement:
                return RuleResult.from_metadata(
                    self.metadata,
                    description=f"Operator '{operator}' incompatible with {field_type} field '{field}' — replaced with '{replacement}'",
                    before={"operator": operator},
                    after={"operator": replacement},
                    location=f"filters[{i}].operator",
                )
        return RuleResult.no_issue("F002", "Filter")
