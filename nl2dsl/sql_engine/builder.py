from sqlalchemy import MetaData, select, func, and_, text, desc, asc
from nl2dsl.dsl.models import DSL


class SQLBuilder:
    def __init__(self, engine, table_mapping: dict[str, str]):
        self._engine = engine
        self._metadata = MetaData()
        self._metadata.reflect(bind=engine)
        self._table_mapping = table_mapping

    def build(self, dsl: DSL) -> str:
        table_name = self._table_mapping.get(dsl.data_source, dsl.data_source)
        table = self._metadata.tables[table_name]

        # Build select columns
        columns = []
        if dsl.dimensions:
            for dim in dsl.dimensions:
                columns.append(table.c[dim])

        if dsl.metrics:
            for metric in dsl.metrics:
                agg_fn = getattr(func, metric.func)
                col = agg_fn(table.c[metric.field]).label(metric.alias or metric.field)
                columns.append(col)

        stmt = select(*columns)

        # Build where
        conditions = []
        if dsl.filters:
            for f in dsl.filters:
                col = table.c[f.field]
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

        if conditions:
            stmt = stmt.where(and_(*conditions))

        # Group by
        if dsl.dimensions and dsl.metrics:
            stmt = stmt.group_by(*[table.c[d] for d in dsl.dimensions])

        # Order by
        if dsl.order_by:
            for ob in dsl.order_by:
                col = table.c.get(ob.field)
                if col is None:
                    if ob.direction == "desc":
                        stmt = stmt.order_by(desc(text(ob.field)))
                    else:
                        stmt = stmt.order_by(asc(text(ob.field)))
                elif ob.direction == "desc":
                    stmt = stmt.order_by(col.desc())
                else:
                    stmt = stmt.order_by(col.asc())

        # Limit
        if dsl.limit:
            stmt = stmt.limit(dsl.limit)
        if dsl.offset:
            stmt = stmt.offset(dsl.offset)

        return str(stmt.compile(self._engine, compile_kwargs={"literal_binds": True}))
