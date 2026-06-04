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


# Time-related keywords for F003
_TIME_KEYWORDS = [
    "本月", "上月", "本周", "上周", "今天", "昨天", "今年", "去年",
    "最近", "过去", "未来", "近期", "当月", "当季",
    "this month", "last month", "this week", "today", "yesterday",
    "recent", "quarter", "Q1", "Q2", "Q3", "Q4",
]


@RuleRegistry.register
class F003_MissingTimeRange(BaseRule):
    """Warn when the original question contains time keywords but DSL lacks time_range."""

    metadata = RuleMetadata(
        error_code="F003",
        category="Filter",
        description="Original question mentions time but DSL has no time_range filter",
        priority=5,
        severity="Warn",
        confidence="medium",
    )

    def check(self, dsl: dict, context) -> RuleResult:
        question = context.original_question or ""
        if not question:
            return RuleResult.no_issue("F003", "Filter")

        # Check if any time keyword appears in the question
        has_time_keyword = any(kw in question for kw in _TIME_KEYWORDS)
        if not has_time_keyword:
            return RuleResult.no_issue("F003", "Filter")

        # Check if DSL already has time constraints
        has_time_range = dsl.get("time_range") is not None
        has_time_field = dsl.get("time_field") is not None

        if not has_time_range and not has_time_field:
            return RuleResult.from_metadata(
                self.metadata,
                description=f"Query contains time keyword but DSL has no time_range or time_field",
                before={"original_question": question},
            )

        return RuleResult.no_issue("F003", "Filter")


@RuleRegistry.register
class F004_ContradictoryFilters(BaseRule):
    """Detect contradictory equality filters on the same field (AND semantics)."""

    metadata = RuleMetadata(
        error_code="F004",
        category="Filter",
        description="Same field has multiple contradictory '=' filter values",
        priority=5,
        severity="Reject",
        confidence="high",
        is_fatal=False,
    )

    def check(self, dsl: dict, context) -> RuleResult:
        filters = dsl.get("filters") or []
        if len(filters) < 2:
            return RuleResult.no_issue("F004", "Filter")

        # Collect equality conditions by field
        eq_conditions: dict[str, list] = {}
        for i, f in enumerate(filters):
            if isinstance(f, dict) and f.get("operator") == "=":
                field = f.get("field", "")
                eq_conditions.setdefault(field, []).append((i, f.get("value")))

        for field, occurrences in eq_conditions.items():
            if len(occurrences) > 1:
                values = [v for _, v in occurrences]
                unique_values = set(str(v) for v in values)
                if len(unique_values) > 1:
                    return RuleResult.from_metadata(
                        self.metadata,
                        description=f"Contradictory filters on '{field}': values {values} (AND semantics — cannot satisfy both)",
                        before={"field": field, "values": values},
                    )

        return RuleResult.no_issue("F004", "Filter")


@RuleRegistry.register
class F005_ValueTypeMismatch(BaseRule):
    """Warn when filter value type doesn't match the field's declared type."""

    metadata = RuleMetadata(
        error_code="F005",
        category="Filter",
        description="Filter value type is incompatible with field type",
        priority=5,
        severity="Warn",
        confidence="low",
    )

    def check(self, dsl: dict, context) -> RuleResult:
        filters = dsl.get("filters") or []
        for i, f in enumerate(filters):
            if not isinstance(f, dict):
                continue
            field = f.get("field", "")
            value = f.get("value")
            if value is None:
                continue

            field_type = context.semantic_config.get_dimension_type(field)
            if field_type == "string":
                continue  # default type, skip

            # Check integer field with non-numeric value
            if field_type in ("integer", "float", "numeric", "number"):
                if isinstance(value, str) and not value.isdigit():
                    return RuleResult.from_metadata(
                        self.metadata,
                        description=f"Value '{value}' for numeric field '{field}' appears to be non-numeric",
                        location=f"filters[{i}].value",
                    )

            # Check boolean field with non-boolean value
            if field_type in ("boolean", "bool"):
                if isinstance(value, str) and value.lower() not in ("true", "false", "0", "1"):
                    return RuleResult.from_metadata(
                        self.metadata,
                        description=f"Value '{value}' for boolean field '{field}' is not boolean-like",
                        location=f"filters[{i}].value",
                    )

        return RuleResult.no_issue("F005", "Filter")
