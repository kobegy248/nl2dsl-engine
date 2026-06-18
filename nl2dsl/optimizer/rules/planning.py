"""Planning rules: P001 (Missing JOIN), P002 (Unnecessary JOIN), P003 (Limit Exceeds), P004(OrderBy)."""

from nl2dsl.optimizer.base import BaseRule, RuleResult
from nl2dsl.optimizer.metadata import RuleMetadata
from nl2dsl.optimizer.registry import RuleRegistry


def _join_table(j) -> str | None:
    """Read the table name from a join that may be a dict or a Join model."""
    if isinstance(j, dict):
        return j.get("table")
    return getattr(j, "table", None)


def _join_on(cfg: dict) -> str:
    """Read the join ``on`` field, tolerating YAML's ``on:`` -> ``True`` quirk.

    PyYAML parses an unquoted ``on:`` key as the boolean ``True`` (YAML 1.1),
    so the config dict ends up as ``{True: "customer_id", "type": ...}``.
    SQLBuilder handles this with ``cfg.get("on", "") or cfg.get(True, "")``;
    P001 mirrors the same fallback so both consumers agree.
    """
    return (cfg.get("on") or cfg.get(True) or "") if isinstance(cfg, dict) else ""


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
            _join_table(j) for j in existing_joins if _join_table(j)
        }

        missing_sources = referenced_sources - {data_source}

        # joins config is a dict keyed by target table: {table: {on, type, alias}}
        # (handle legacy list form defensively).
        joins_config = context.semantic_config.get_joins_for_source(data_source)
        joins_dict: dict[str, dict] = {}
        if isinstance(joins_config, dict):
            joins_dict = {
                t: cfg for t, cfg in joins_config.items() if isinstance(cfg, dict)
            }
        elif isinstance(joins_config, list):
            for jc in joins_config:
                if isinstance(jc, dict) and jc.get("table"):
                    joins_dict[jc["table"]] = jc

        alias_to_table: dict[str, str] = {
            cfg.get("alias"): t
            for t, cfg in joins_dict.items()
            if cfg.get("alias")
        }

        # Resolve each missing source to a physical table and check reachability.
        needed_tables: set[str] = set()
        unresolved: list[str] = []
        for src in missing_sources:
            table = context.semantic_config.get_table_for_source(src)
            if not table or table in joined_tables:
                continue
            if table in joins_dict:
                needed_tables.add(table)
            else:
                unresolved.append(table)

        # Resolve dependency chains: a join whose `on` is qualified like
        # "p.supplier_id" requires the table behind alias "p" (e.g. product_dim)
        # to be joined first. SQLBuilder's direct join loop trusts dsl.joins
        # order, so P001 must emit the full ordered chain.
        def _resolve_deps(table: str, visited: set[str]) -> None:
            if table in visited:
                return
            visited.add(table)
            cfg = joins_dict.get(table, {})
            on_field = _join_on(cfg)
            if "." in on_field:
                alias = on_field.split(".", 1)[0]
                dep = alias_to_table.get(alias)
                if dep and dep in joins_dict:
                    needed_tables.add(dep)
                    _resolve_deps(dep, visited)

        for t in list(needed_tables):
            _resolve_deps(t, set())

        if not needed_tables and not unresolved:
            return RuleResult.no_issue("P001", "Planning")

        if not needed_tables:
            # No declared JOIN path reaches the needed tables
            return RuleResult(
                error_code=self.metadata.error_code,
                category=self.metadata.category,
                severity="Warn",
                confidence="low",
                description=(
                    f"Tables {unresolved} are needed but no JOIN path found "
                    f"from '{data_source}'"
                ),
                candidate_values=unresolved,
            )

        # Build the join list in dependency order (upstream tables first).
        ordered: list[dict] = []
        added: set[str] = set()

        def _add(table: str) -> None:
            if table in added or table not in needed_tables:
                return
            cfg = joins_dict.get(table, {})
            on_field = _join_on(cfg)
            if "." in on_field:
                dep = alias_to_table.get(on_field.split(".", 1)[0])
                if dep and dep in needed_tables:
                    _add(dep)
            ordered.append(
                {
                    "table": table,
                    "on_field": on_field,
                    "join_type": cfg.get("type", "left"),
                    "alias": cfg.get("alias"),
                }
            )
            added.add(table)

        for t in sorted(needed_tables):
            _add(t)

        after = list(existing_joins) + ordered
        injected_names = [j["table"] for j in ordered]
        return RuleResult.from_metadata(
            self.metadata,
            description=(
                f"Injected JOIN(s) {injected_names} from '{data_source}' "
                f"to reach cross-table dimension(s)/metric(s)"
            ),
            confidence="high",
            before={"joins": dsl.get("joins")},
            after={"joins": after},
            location="joins",
        )
