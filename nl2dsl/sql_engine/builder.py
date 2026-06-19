import re
from sqlalchemy import MetaData, select, func, and_, or_, not_, desc, asc, text, literal, column, join as sa_join
from nl2dsl.dsl.models import DSL, Join
from nl2dsl.exceptions import ValidationError


# Valid SQL aggregation function names (whitelist)
_VALID_AGG_FUNCS = {"sum", "avg", "count", "min", "max"}


class SQLBuilder:
    def __init__(self, engine, table_mapping: dict[str, str], data_sources: dict | None = None, dimension_mapping: dict[str, str] | None = None):
        self._engine = engine
        self._metadata = MetaData()
        self._metadata.reflect(bind=engine)
        self._table_mapping = table_mapping
        self._data_sources = data_sources or {}
        self._dimension_mapping = dimension_mapping or {}

    def _parse_expr(self, expr: str) -> tuple[str, str]:
        """Parse 'SUM(order_amount)' -> ('sum', 'order_amount').

        Also supports complex inner expressions like 'SUM(CASE WHEN x THEN y END)'.
        Raises ValidationError if expression is malformed or unsafe.
        """
        match = re.match(r"^([A-Za-z_]+)\((.+)\)$", expr)
        if not match:
            raise ValidationError(f"Invalid metric expression: {expr}")
        func_name = match.group(1).lower()
        inner = match.group(2).strip()
        if func_name not in _VALID_AGG_FUNCS:
            raise ValidationError(f"Unsupported aggregation function: {func_name}")
        return func_name, inner

    def _resolve_column(self, tables: dict[str, object], field: str) -> object:
        """Resolve a column reference across multiple tables.

        Supports qualified references like 'table.column'.
        Falls back to first table that contains the column.
        Also resolves semantic dimension names to physical column names.
        For SQL expressions (e.g. CASE WHEN...), returns a text() literal.
        """
        # Map semantic name to physical column name
        physical_field = self._dimension_mapping.get(field, field)

        # If the field looks like a SQL expression (contains spaces or SQL keywords),
        # wrap it in text() so SQLAlchemy treats it as a literal expression.
        if " " in physical_field or any(
            kw in physical_field.upper() for kw in ("CASE", "WHEN", "THEN", "ELSE", "END", "COALESCE", "NULLIF", "CAST")
        ):
            return text(physical_field)

        if "." in physical_field:
            table_name, col_name = physical_field.split(".", 1)
            # Try to match by alias name first, then original table name
            for tbl in tables.values():
                names = [tbl.name]
                if hasattr(tbl, "element"):
                    names.append(tbl.element.name)
                if table_name in names and hasattr(tbl, "c") and col_name in tbl.c:
                    return tbl.c[col_name]
            raise ValidationError(f"Column '{field}' not found in any table")

        # Unqualified: search all tables
        for tbl in tables.values():
            if hasattr(tbl, "c") and physical_field in tbl.c:
                return tbl.c[physical_field]
        raise ValidationError(f"Column '{field}' not found in any table")

    def _get_table_for_column(self, tables: dict[str, object], field: str) -> object:
        """Get the table object that contains the given column."""
        if "." in field:
            table_name, col_name = field.split(".", 1)
            for tbl in tables.values():
                names = [tbl.name]
                if hasattr(tbl, "element"):
                    names.append(tbl.element.name)
                if table_name in names and hasattr(tbl, "c") and col_name in tbl.c:
                    return tbl
            raise ValidationError(f"Table for column '{field}' not found")

        for tbl in tables.values():
            if hasattr(tbl, "c") and field in tbl.c:
                return tbl
        raise ValidationError(f"Table for column '{field}' not found")

    def _build_condition_tree(self, tables: dict[str, object], node) -> object:
        """Recursively build SQLAlchemy expression from a filter tree."""
        from nl2dsl.dsl.models import FilterTreeNode

        if isinstance(node, FilterTreeNode):
            if node.op == "and":
                return and_(*[self._build_condition_tree(tables, c) for c in node.children])
            elif node.op == "or":
                return or_(*[self._build_condition_tree(tables, c) for c in node.children])
            elif node.op == "not":
                return not_(self._build_condition_tree(tables, node.children[0]))
        # Leaf node
        return self._build_leaf_condition(tables, node)

    def _build_leaf_condition(self, tables: dict[str, object], f) -> object:
        """Build a single filter condition (leaf node)."""
        col = self._resolve_column(tables, f.field)
        if f.operator == "=":
            return col == f.value
        elif f.operator == "!=":
            return col != f.value
        elif f.operator == ">":
            return col > f.value
        elif f.operator == "<":
            return col < f.value
        elif f.operator == ">=":
            return col >= f.value
        elif f.operator == "<=":
            return col <= f.value
        elif f.operator == "in":
            return col.in_(f.value)
        elif f.operator == "like":
            return col.like(f"%{f.value}%")
        elif f.operator == "between":
            val = f.value
            if isinstance(val, (list, tuple)) and len(val) == 2:
                return col.between(val[0], val[1])
            raise ValidationError(f"'between' requires [min, max] list, got {val!r}")
        elif f.operator == "is_null":
            return col.is_(None)
        else:
            raise ValidationError(f"Unknown operator: {f.operator}")

    def _collect_columns_from_tree(self, node, columns: set) -> None:
        """Recursively collect field names from a filter tree."""
        from nl2dsl.dsl.models import FilterTreeNode

        if isinstance(node, FilterTreeNode):
            for child in node.children:
                self._collect_columns_from_tree(child, columns)
        else:
            columns.add(node.field)

    def _collect_referenced_columns(self, dsl: DSL) -> set[str]:
        """Collect all physical column names referenced in the DSL."""
        columns: set[str] = set()

        # Dimensions (semantic -> physical)
        if dsl.dimensions:
            for dim in dsl.dimensions:
                physical = self._dimension_mapping.get(dim, dim)
                columns.add(physical)

        # Metrics — only simple column references need table resolution
        if dsl.metrics:
            for metric in dsl.metrics:
                if "(" in metric.field:
                    func_name, inner = self._parse_expr(metric.field)
                    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", inner):
                        columns.add(inner)
                else:
                    columns.add(metric.field)

        # Filters
        if dsl.filters:
            if isinstance(dsl.filters, list):
                for f in dsl.filters:
                    columns.add(f.field)
            else:
                self._collect_columns_from_tree(dsl.filters, columns)

        # Time field
        if dsl.time_field:
            columns.add(dsl.time_field)

        # Order by
        if dsl.order_by:
            for ob in dsl.order_by:
                columns.add(ob.field)

        return columns

    def _determine_required_joins(self, dsl: DSL, referenced_columns: set[str]) -> list[Join]:
        """Determine the minimal set of joins needed for referenced columns."""
        ds_joins = self._data_sources.get(dsl.data_source, {}).get("joins", {})
        if not ds_joins:
            return []

        primary_table_name = self._table_mapping.get(dsl.data_source, dsl.data_source)
        primary_table = self._metadata.tables.get(primary_table_name)
        if primary_table is None:
            return []

        primary_cols = set(primary_table.c.keys())

        # Build alias -> table_name mapping
        alias_to_table: dict[str, str] = {}
        for table_name, cfg in ds_joins.items():
            alias = cfg.get("alias")
            if alias:
                alias_to_table[alias] = table_name

        def find_join_table(col_name: str) -> str | None:
            """Find which configured join table contains a column; None if in primary."""
            if col_name in primary_cols:
                return None
            for table_name, cfg in ds_joins.items():
                join_table = self._metadata.tables.get(table_name)
                if join_table is not None and col_name in join_table.c:
                    return table_name
            return None

        required_tables: set[str] = set()

        for col_ref in referenced_columns:
            if "." in col_ref:
                # Qualified reference like "p.supplier_id"
                alias, _ = col_ref.split(".", 1)
                dep_table = alias_to_table.get(alias)
                if dep_table and dep_table in ds_joins:
                    required_tables.add(dep_table)
                continue

            table_name = find_join_table(col_ref)
            if table_name:
                required_tables.add(table_name)

        # Resolve dependency chains (e.g. supplier_dim on p.supplier_id requires product_dim)
        def resolve_deps(table_name: str, visited: set[str] | None = None) -> None:
            if visited is None:
                visited = set()
            if table_name in visited:
                return
            visited.add(table_name)

            cfg = ds_joins.get(table_name)
            if not cfg:
                return

            on_field = cfg.get("on", "") or cfg.get(True, "")
            if "." in on_field:
                alias, _ = on_field.split(".", 1)
                dep_table = alias_to_table.get(alias)
                if dep_table and dep_table in ds_joins:
                    required_tables.add(dep_table)
                    resolve_deps(dep_table, visited)

        for table_name in list(required_tables):
            resolve_deps(table_name)

        # Build Join objects in dependency order
        joins: list[Join] = []
        added: set[str] = set()

        def add_join(table_name: str) -> None:
            if table_name in added or table_name not in required_tables:
                return
            cfg = ds_joins[table_name]
            on_field = cfg.get("on", "") or cfg.get(True, "")

            # Add dependencies first
            if "." in on_field:
                alias, _ = on_field.split(".", 1)
                dep_table = alias_to_table.get(alias)
                if dep_table and dep_table in required_tables:
                    add_join(dep_table)

            joins.append(Join(
                table=table_name,
                on_field=on_field,
                join_type=cfg.get("type", "left"),
                alias=cfg.get("alias"),
            ))
            added.add(table_name)

        for table_name in required_tables:
            add_join(table_name)

        return joins

    def build(self, dsl: DSL) -> str:
        primary_table_name = self._table_mapping.get(dsl.data_source, dsl.data_source)
        primary_table = self._metadata.tables.get(primary_table_name)
        if primary_table is None:
            raise ValidationError(f"Primary table '{primary_table_name}' not found in database")

        # Collect all tables involved
        tables: dict[str, object] = {primary_table_name: primary_table}
        join_clauses = []

        # Auto-infer joins from data_source config if dsl.joins is empty
        joins = list(dsl.joins) if dsl.joins else []
        if not joins and dsl.data_source in self._data_sources:
            referenced = self._collect_referenced_columns(dsl)
            joins = self._determine_required_joins(dsl, referenced)

        if joins:
            for j in joins:
                join_table_name = j.table
                join_table = self._metadata.tables.get(join_table_name)
                if join_table is None:
                    raise ValidationError(f"Join table '{join_table_name}' not found in database")
                join_table_ref = join_table.alias(j.alias) if j.alias else join_table
                tables[join_table_name] = join_table_ref

                # Resolve join condition columns
                on_col_primary = self._resolve_column(tables, j.on_field)
                # For simplicity, assume join on primary table's matching column
                # If on_field is qualified (e.g., "customer_dim.customer_id"), use that
                if "." in j.on_field:
                    _, col_name = j.on_field.split(".", 1)
                    primary_col = primary_table.c.get(col_name)
                    if primary_col is None:
                        primary_col = self._resolve_column(tables, col_name)
                else:
                    primary_col = primary_table.c.get(j.on_field)
                    if primary_col is None:
                        primary_col = self._resolve_column(tables, j.on_field)
                if j.join_type == "left":
                    join_clauses.append((join_table_ref, on_col_primary == join_table_ref.c.get(
                        j.on_field.split(".")[-1] if "." in j.on_field else j.on_field
                    )))
                elif j.join_type == "right":
                    join_clauses.append((join_table_ref, on_col_primary == join_table_ref.c.get(
                        j.on_field.split(".")[-1] if "." in j.on_field else j.on_field
                    )))
                else:
                    join_clauses.append((join_table_ref, on_col_primary == join_table_ref.c.get(
                        j.on_field.split(".")[-1] if "." in j.on_field else j.on_field
                    )))

        # Build select columns
        columns = []
        if dsl.dimensions:
            for dim in dsl.dimensions:
                # Map semantic name to physical column if available
                physical_col = self._dimension_mapping.get(dim, dim)
                col = self._resolve_column(tables, physical_col)
                # Label with original semantic name so result keys match
                columns.append(col.label(dim))

        if dsl.metrics:
            for metric in dsl.metrics:
                if "(" in metric.field:
                    func_name, inner = self._parse_expr(metric.field)
                    agg_fn = getattr(func, func_name)
                    # Simple column name vs complex expression (CASE WHEN etc.)
                    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", inner):
                        col = self._resolve_column(tables, inner)
                        columns.append(agg_fn(col).label(metric.alias or metric.field))
                    else:
                        columns.append(agg_fn(text(inner)).label(metric.alias or metric.field))
                else:
                    agg_fn = getattr(func, metric.func)
                    col = self._resolve_column(tables, metric.field)
                    columns.append(agg_fn(col).label(metric.alias or metric.field))

        # Build FROM clause with joins
        if join_clauses:
            from_clause = primary_table
            for join_table_ref, join_condition in join_clauses:
                from_clause = from_clause.join(join_table_ref, join_condition)
            stmt = select(*columns).select_from(from_clause)
        else:
            stmt = select(*columns).select_from(primary_table)

        # Build where
        conditions = []

        # time_range -> between condition
        if dsl.time_field and dsl.time_range:
            time_col = self._resolve_column(tables, dsl.time_field)
            conditions.append(time_col.between(dsl.time_range[0], dsl.time_range[1]))

        # filters: flat list or condition tree
        if dsl.filters:
            if isinstance(dsl.filters, list):
                for f in dsl.filters:
                    conditions.append(self._build_leaf_condition(tables, f))
            else:
                conditions.append(self._build_condition_tree(tables, dsl.filters))

        if conditions:
            stmt = stmt.where(and_(*conditions))

        # Group by
        if dsl.dimensions and dsl.metrics:
            group_cols = [self._resolve_column(tables, self._dimension_mapping.get(d, d)) for d in dsl.dimensions]
            stmt = stmt.group_by(*group_cols)

        # Having
        if dsl.having:
            having_conditions = []
            for h in dsl.having:
                # Whitelist validation: alias must be alphanumeric + underscore
                if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", h.field):
                    raise ValidationError(
                        f"Invalid having field name: {h.field!r}. "
                        f"Must be a valid metric alias (letters, digits, underscores only)."
                    )
                col_ref = column(h.field)
                val = literal(h.value)
                if h.operator == "=":
                    having_conditions.append(col_ref == val)
                elif h.operator == "!=":
                    having_conditions.append(col_ref != val)
                elif h.operator == ">":
                    having_conditions.append(col_ref > val)
                elif h.operator == "<":
                    having_conditions.append(col_ref < val)
                elif h.operator == ">=":
                    having_conditions.append(col_ref >= val)
                elif h.operator == "<=":
                    having_conditions.append(col_ref <= val)
                elif h.operator == "between":
                    bval = h.value
                    if isinstance(bval, (list, tuple)) and len(bval) == 2:
                        having_conditions.append(
                            col_ref.between(literal(bval[0]), literal(bval[1]))
                        )
                    else:
                        raise ValidationError(
                            f"'between' in having requires [min, max] list, got {bval!r}"
                        )
                else:
                    raise ValidationError(f"Unknown operator in having: {h.operator}")
            if having_conditions:
                stmt = stmt.having(and_(*having_conditions))

        # Collect metric aliases for ORDER BY resolution
        metric_aliases = {m.alias for m in (dsl.metrics or []) if m.alias}

        # Order by
        if dsl.order_by:
            for ob in dsl.order_by:
                try:
                    col = self._resolve_column(tables, ob.field)
                    if ob.direction == "desc":
                        stmt = stmt.order_by(col.desc())
                    else:
                        stmt = stmt.order_by(col.asc())
                except ValidationError:
                    if ob.field in metric_aliases:
                        if ob.direction == "desc":
                            stmt = stmt.order_by(desc(text(ob.field)))
                        else:
                            stmt = stmt.order_by(asc(text(ob.field)))
                    else:
                        raise

        # Post-processing needs the complete grouped result. Applying a global
        # SQL LIMIT first would turn "top N per group" into "top N overall" and
        # would also corrupt a proportion denominator.
        if dsl.limit and dsl.post_process is None:
            stmt = stmt.limit(dsl.limit)
        if dsl.offset:
            stmt = stmt.offset(dsl.offset)

        return str(stmt.compile(self._engine, compile_kwargs={"literal_binds": True}))
