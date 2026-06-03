"""Planning rules: P001 (Missing JOIN), P002 (Unnecessary JOIN), P003 (Limit Exceeds), P004 (OrderBy)."""

from nl2dsl.optimizer.base import BaseRule, RuleResult
from nl2dsl.optimizer.metadata import RuleMetadata
from nl2dsl.optimizer.registry import RuleRegistry


@RuleRegistry.register
class P002_UnnecessaryJoin(BaseRule):
    """Warn if a JOIN table is not referenced by any metric or dimension."""

    metadata = RuleMetadata(
        error_code="P002",
        category="Planning",
        description="JOIN references a table not used by any metric or dimension",
        priority=5,
        severity="Warn",
        confidence="high",
    )

    def check(self, dsl: dict, context) -> RuleResult:
        joins = dsl.get("joins") or []
        if not joins:
            return RuleResult.no_issue("P002", "Planning")

        # Collect all referenced tables from metrics and dimensions
        data_source = dsl.get("data_source", "")
        referenced_tables = {context.semantic_config.get_table_for_source(data_source)}

        for m in (dsl.get("metrics") or []):
            alias = m.get("alias", "")
            if alias:
                src = context.semantic_config.find_data_source_for_metric(alias)
                if src:
                    referenced_tables.add(context.semantic_config.get_table_for_source(src))

        for d in (dsl.get("dimensions") or []):
            if d:
                src = context.semantic_config.find_data_source_for_dimension(d)
                if src:
                    referenced_tables.add(context.semantic_config.get_table_for_source(src))

        for i, join in enumerate(joins):
            if isinstance(join, dict):
                table = join.get("table", "")
                if table and table not in referenced_tables:
                    return RuleResult.from_metadata(
                        self.metadata,
                        description=f"JOIN on table '{table}' is not referenced by any metric or dimension",
                        location=f"joins[{i}]",
                    )

        return RuleResult.no_issue("P002", "Planning")


@RuleRegistry.register
class P003_LimitExceedsMax(BaseRule):
    """Fix limit that exceeds the configured maximum."""

    metadata = RuleMetadata(
        error_code="P003",
        category="Planning",
        description="Query limit exceeds maximum allowed value",
        priority=5,
        severity="Fix",
        confidence="high",
        auto_fixable=True,
    )

    def check(self, dsl: dict, context) -> RuleResult:
        limit = dsl.get("limit", 100)
        max_limit = context.max_limit

        if limit is not None and limit > max_limit:
            return RuleResult.from_metadata(
                self.metadata,
                description=f"Limit {limit} exceeds maximum {max_limit} — truncated to {max_limit}",
                before={"limit": limit},
                after={"limit": max_limit},
                location="limit",
            )
        return RuleResult.no_issue("P003", "Planning")


@RuleRegistry.register
class P004_OrderByNotInOutput(BaseRule):
    """Warn if order_by field is not in metrics aliases or dimensions."""

    metadata = RuleMetadata(
        error_code="P004",
        category="Planning",
        description="ORDER BY field is not present in metrics or dimensions",
        priority=5,
        severity="Warn",
        confidence="medium",
    )

    def check(self, dsl: dict, context) -> RuleResult:
        order_by = dsl.get("order_by") or []
        if not order_by:
            return RuleResult.no_issue("P004", "Planning")

        # Collect valid output fields
        metric_aliases = {m.get("alias", "") for m in (dsl.get("metrics") or [])}
        metric_fields = {m.get("field", "") for m in (dsl.get("metrics") or [])}
        dimensions = set(dsl.get("dimensions") or [])

        valid_fields = metric_aliases | metric_fields | dimensions
        valid_fields.discard("")

        for i, ob in enumerate(order_by):
            if isinstance(ob, dict):
                field = ob.get("field", "")
                if field and field not in valid_fields:
                    return RuleResult.from_metadata(
                        self.metadata,
                        description=f"ORDER BY field '{field}' is not in metrics or dimensions",
                        location=f"order_by[{i}].field",
                    )

        return RuleResult.no_issue("P004", "Planning")


@RuleRegistry.register
class P001_MissingRequiredJoin(BaseRule):
    """Detect when metrics and dimensions span multiple tables without a JOIN.

    - Unique JOIN path => Fix (inject JOIN with high confidence)
    - Multiple JOIN paths => Warn (list candidates with medium confidence)
    - No JOIN path => Warn
    """

    metadata = RuleMetadata(
        error_code="P001",
        category="Planning",
        description="Metrics and dimensions span multiple tables but DSL lacks a JOIN",
        priority=5,
        severity="Fix",
        confidence="high",
        auto_fixable=True,
    )

    def check(self, dsl: dict, context) -> RuleResult:
        data_source = dsl.get("data_source", "")
        if not data_source:
            return RuleResult.no_issue("P001", "Planning")

        # Collect all data sources referenced by metrics and dimensions
        referenced_sources = set()

        for m in (dsl.get("metrics") or []):
            alias = m.get("alias", "")
            if alias:
                src = context.semantic_config.find_data_source_for_metric(alias)
                if src:
                    referenced_sources.add(src)

        for d in (dsl.get("dimensions") or []):
            if d:
                src = context.semantic_config.find_data_source_for_dimension(d)
                if src:
                    referenced_sources.add(src)

        # Only the current data_source is referenced => no JOIN needed
        if referenced_sources <= {data_source} or not referenced_sources:
            return RuleResult.no_issue("P001", "Planning")

        # Other sources are referenced => need JOIN(s)
        existing_joins = dsl.get("joins") or []
        joined_tables = {
            j.get("table", "") for j in existing_joins if isinstance(j, dict)
        }

        missing_sources = referenced_sources - {data_source}
        missing_tables = set()
        join_candidates = []

        for src in missing_sources:
            table = context.semantic_config.get_table_for_source(src)
            if table and table not in joined_tables:
                missing_tables.add(table)
                # Look for JOIN paths from the current data_source
                joins_config = context.semantic_config.get_joins_for_source(data_source)
                for jc in joins_config:
                    if isinstance(jc, dict) and jc.get("table") == table:
                        join_candidates.append(jc)

        if not missing_tables:
            return RuleResult.no_issue("P001", "Planning")

        if len(join_candidates) == 1:
            # Unique path => auto-fix
            jc = join_candidates[0]
            new_join = {
                "table": jc.get("table", list(missing_tables)[0]),
                "on_field": jc.get("on_field", "id"),
                "join_type": jc.get("join_type", "inner"),
            }
            existing_joins.append(new_join)
            return RuleResult.from_metadata(
                self.metadata,
                description=f"Injected JOIN on '{new_join['table']}' via '{new_join['on_field']}'",
                confidence="high",
                before={"joins": dsl.get("joins")},
                after={"joins": existing_joins},
                location="joins",
            )

        if len(join_candidates) > 1:
            # Multiple paths => warn with candidates
            tables = [jc.get("table", "?") for jc in join_candidates]
            return RuleResult.from_metadata(
                self.metadata,
                severity="Warn",
                confidence="medium",
                description=f"Multiple JOIN paths to tables {missing_tables}: candidates {tables}",
                candidate_values=tables,
            )

        # No known path => warn
        return RuleResult.from_metadata(
            self.metadata,
            severity="Warn",
            confidence="low",
            description=f"Tables {missing_tables} are needed but no JOIN path found from '{data_source}'",
        )
