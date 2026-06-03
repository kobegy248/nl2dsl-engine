"""Filter rules: F001 (Invalid Enum), F002 (Operator-Type Mismatch), F003-F005."""

try:
    from Levenshtein import distance as levenshtein_distance
except ImportError:
    # Fallback: simple edit distance for short strings
    def levenshtein_distance(a: str, b: str) -> int:
        """Simple Levenshtein distance implementation."""
        if len(a) < len(b):
            return levenshtein_distance(b, a)
        if len(b) == 0:
            return len(a)
        prev_row = list(range(len(b) + 1))
        for i, c1 in enumerate(a):
            curr_row = [i + 1]
            for j, c2 in enumerate(b):
                insertions = prev_row[j + 1] + 1
                deletions = curr_row[j] + 1
                substitutions = prev_row[j] + (c1 != c2)
                curr_row.append(min(insertions, deletions, substitutions))
            prev_row = curr_row
        return prev_row[-1]


def _fuzzy_match_value(user_value: str, candidates: list[str]) -> tuple[str | None, str]:
    """Fuzzy match a user value against candidate values.

    Strategy (in order):
    1. Exact match → high confidence
    2. Prefix match → high confidence
    3. Edit distance ≤ 1 → high confidence
    4. Edit distance ≤ 2 → medium confidence
    5. No match → low confidence

    Returns: (matched_value_or_None, confidence)
    """
    if not user_value or not candidates:
        return None, "low"

    user_lower = str(user_value).lower().strip()
    candidates_lower = [(c, str(c).lower().strip()) for c in candidates]

    # 1. Exact match (case-insensitive)
    for orig, lower in candidates_lower:
        if lower == user_lower:
            return orig, "high"

    # 2. Prefix match
    for orig, lower in candidates_lower:
        if lower.startswith(user_lower) or user_lower.startswith(lower):
            return orig, "high"

    # 3. Edit distance ≤ 1
    for orig, lower in candidates_lower:
        try:
            if levenshtein_distance(user_lower, lower) <= 1:
                return orig, "high"
        except Exception:
            pass

    # 4. Edit distance ≤ 2
    for orig, lower in candidates_lower:
        try:
            if levenshtein_distance(user_lower, lower) <= 2:
                return orig, "medium"
        except Exception:
            pass

    # 5. No match
    return None, "low"


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


@RuleRegistry.register
class F001_InvalidEnumValue(BaseRule):
    """Check filter values against dimension value_maps. Auto-correct with fuzzy matching."""

    metadata = RuleMetadata(
        error_code="F001",
        category="Filter",
        description="Filter value does not match registered enum values — fuzzy fix",
        priority=3,
        severity="Fix",
        confidence="medium",
        auto_fixable=True,
    )

    def check(self, dsl: dict, context) -> RuleResult:
        filters = dsl.get("filters") or []
        if not filters:
            return RuleResult.no_issue("F001", "Filter")

        for i, f in enumerate(filters):
            if not isinstance(f, dict):
                continue
            field = f.get("field", "")
            operator = f.get("operator", "=")
            value = f.get("value")

            if value is None:
                continue
            if operator not in ("=", "in"):
                continue

            # Check value_map
            value_map = context.semantic_config.get_value_map(field)
            values_list = context.semantic_config.get_values(field)

            candidates = None
            if value_map:
                candidates = list(value_map.keys())
            elif values_list:
                candidates = [str(v) for v in values_list]

            if not candidates:
                continue

            # For 'in' operator, check each value
            if operator == "in" and isinstance(value, list):
                for j, v in enumerate(value):
                    if str(v) not in [str(c) for c in candidates]:
                        matched, confidence = _fuzzy_match_value(str(v), candidates)
                        if matched and confidence in ("high", "medium"):
                            new_values = list(value)
                            new_values[j] = matched
                            return RuleResult.from_metadata(
                                self.metadata,
                                description=f"Enum value '{v}' corrected to '{matched}' for field '{field}' (edit distance matched)",
                                confidence=confidence,
                                before={"value": value},
                                after={"value": new_values},
                                location=f"filters[{i}].value",
                            )
            # For '=' operator, check single value
            elif str(value) not in [str(c) for c in candidates]:
                matched, confidence = _fuzzy_match_value(str(value), candidates)
                if matched and confidence in ("high", "medium"):
                    return RuleResult.from_metadata(
                        self.metadata,
                        description=f"Enum value '{value}' corrected to '{matched}' for field '{field}' (edit distance matched)",
                        confidence=confidence,
                        before={"value": value},
                        after={"value": matched},
                        location=f"filters[{i}].value",
                    )

        return RuleResult.no_issue("F001", "Filter")
