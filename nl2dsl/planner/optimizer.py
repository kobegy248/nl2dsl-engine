from __future__ import annotations

from nl2dsl.dsl.models import DSL


class QueryOptimizer:
    def optimize(self, dsl: DSL) -> DSL:
        # TODO: implement predicate pushdown, projection pushdown, etc.
        return dsl
