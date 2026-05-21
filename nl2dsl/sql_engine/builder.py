import re
from sqlalchemy import MetaData, select, func, and_, desc, asc, text, join as sa_join
from nl2dsl.dsl.models import DSL
from nl2dsl.exceptions import ValidationError


# Valid SQL aggregation function names (whitelist)
_VALID_AGG_FUNCS = {"sum", "avg", "count", "min", "max"}


class SQLBuilder:
    def __init__(self, engine, table_mapping: dict[str, str]):
        self._engine = engine
        self._metadata = MetaData()
        self._metadata.reflect(bind=engine)
        self._table_mapping = table_mapping

    def _parse_expr(self, expr: str) -> tuple[str, str]:
        """Parse 'SUM(order_amount)' -> ('sum', 'order_amount').

        Raises ValidationError if expression is malformed or unsafe.
        """
        match = re.match(r"^([A-Za-z_]+)\(([A-Za-z_][A-Za-z0-9_]*)\)$", expr)
        if not match:
            raise ValidationError(f"Invalid metric expression: {expr}")
        func_name = match.group(1).lower()
        column_name = match.group(2)
        if func_name not in _VALID_AGG_FUNCS:
            raise ValidationError(f"Unsupported aggregation function: {func_name}")
        return func_name, column_name

    def _resolve_column(self, tables: dict[str, object], field: str) -> object:
        """Resolve a column reference across multiple tables.

        Supports qualified references like 'table.column'.
        Falls back to first table that contains the column.
        """
        if "." in field:
            table_name, col_name = field.split(".", 1)
            # Try to match by table name or alias (handles SQLAlchemy Alias elements)
            for tbl in tables.values():
                raw_name = tbl.name
                if hasattr(tbl, "element"):
                    raw_name = tbl.element.name
                if raw_name == table_name and hasattr(tbl, "c") and col_name in tbl.c:
                    return tbl.c[col_name]
            raise ValidationError(f"Column '{field}' not found in any table")

        # Unqualified: search all tables
        for tbl in tables.values():
            if hasattr(tbl, "c") and field in tbl.c:
                return tbl.c[field]
        raise ValidationError(f"Column '{field}' not found in any table")

    def _get_table_for_column(self, tables: dict[str, object], field: str) -> object:
        """Get the table object that contains the given column."""
        if "." in field:
            table_name, col_name = field.split(".", 1)
            for tbl in tables.values():
                raw_name = tbl.name
                if hasattr(tbl, "element"):
                    raw_name = tbl.element.name
                if raw_name == table_name and hasattr(tbl, "c") and col_name in tbl.c:
                    return tbl
            raise ValidationError(f"Table for column '{field}' not found")

        for tbl in tables.values():
            if hasattr(tbl, "c") and field in tbl.c:
                return tbl
        raise ValidationError(f"Table for column '{field}' not found")

    def build(self, dsl: DSL) -> str:
        primary_table_name = self._table_mapping.get(dsl.data_source, dsl.data_source)
        primary_table = self._metadata.tables.get(primary_table_name)
        if primary_table is None:
            raise ValidationError(f"Primary table '{primary_table_name}' not found in database")

        # Collect all tables involved
        tables: dict[str, object] = {primary_table_name: primary_table}
        join_clauses = []

        if dsl.joins:
            for j in dsl.joins:
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
                col = self._resolve_column(tables, dim)
                columns.append(col)

        if dsl.metrics:
            for metric in dsl.metrics:
                if "(" in metric.field:
                    func_name, col_name = self._parse_expr(metric.field)
                    agg_fn = getattr(func, func_name)
                    col = self._resolve_column(tables, col_name)
                    columns.append(agg_fn(col).label(metric.alias or metric.field))
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
        if dsl.filters:
            for f in dsl.filters:
                col = self._resolve_column(tables, f.field)
                if f.operator == "=":
                    conditions.append(col == f.value)
                elif f.operator == "!=":
                    conditions.append(col != f.value)
                elif f.operator == ">":
                    conditions.append(col > f.value)
                elif f.operator == "<":
                    conditions.append(col < f.value)
                elif f.operator == ">=":
                    conditions.append(col >= f.value)
                elif f.operator == "<=":
                    conditions.append(col <= f.value)
                elif f.operator == "in":
                    conditions.append(col.in_(f.value))
                elif f.operator == "like":
                    conditions.append(col.like(f"%{f.value}%"))

        if conditions:
            stmt = stmt.where(and_(*conditions))

        # Group by
        if dsl.dimensions and dsl.metrics:
            group_cols = [self._resolve_column(tables, d) for d in dsl.dimensions]
            stmt = stmt.group_by(*group_cols)

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

        # Limit
        if dsl.limit:
            stmt = stmt.limit(dsl.limit)
        if dsl.offset:
            stmt = stmt.offset(dsl.offset)

        return str(stmt.compile(self._engine, compile_kwargs={"literal_binds": True}))
