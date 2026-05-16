from __future__ import annotations

from nl2dsl.dsl.models import DSL


class QueryRouter:
    def route(self, dsl: DSL) -> str:
        # TODO: implement routing to pre-aggregated tables, cache, etc.
        return dsl.data_source
