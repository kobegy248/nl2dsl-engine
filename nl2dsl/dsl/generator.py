"""DSL Generator abstraction and retry chain.

Provides:
- DSLGenerator: abstract base for all DSL generation strategies
- RuleBasedDSLGenerator: keyword-based mock generator (for tests/fallback)
- RetryChain: wraps any generator with error feedback + retry logic
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Callable

from nl2dsl.dsl.models import DSL, Aggregation, Filter, OrderBy, PostProcess
from nl2dsl.exceptions import ValidationError
from nl2dsl.query.time_resolver import resolve_time


# Negation cues that, when preceding a value, flip an equality to `!=`.
_NEGATION_CUES = ("非", "不是", "排除", "除外", "不包含", "不含")


def _is_negated(question: str, keyword: str) -> bool:
    """True if ``keyword`` is preceded (within 4 chars) by a negation cue."""
    idx = question.find(keyword)
    while idx != -1:
        prefix = question[max(0, idx - 4):idx]
        if any(cue in prefix for cue in _NEGATION_CUES):
            return True
        idx = question.find(keyword, idx + 1)
    return False


class DSLGenerator(ABC):
    """Abstract base for DSL generation strategies."""

    @abstractmethod
    def generate(self, question: str, data_source: str | None = None) -> DSL:
        """Generate DSL from natural language question."""
        ...


class RuleBasedDSLGenerator(DSLGenerator):
    """Keyword-based DSL generator (mock/fallback implementation).

    Uses hardcoded keyword matching for metrics, dimensions, filters.
    Suitable for testing environments without LLM.
    """

    def __init__(self, registry: dict | None = None):
        self._registry = registry or {}

    def generate(self, question: str, data_source: str | None = None) -> DSL:
        """Generate DSL from natural language question.

        Registry-aware dispatch (P0: bank / supply_chain infinite-recursion fix):

        - When the registry is the ecommerce sample registry, use the ecommerce
          keyword rules (unchanged) — preserves existing ecommerce behaviour.
        - For any other domain (bank / supply_chain / ...), select
          ``data_source`` / metric alias / dimension **from that domain's
          registry** via description keyword matching, so the generated DSL is
          valid and executable against the domain's schema. Never invents
          ecommerce metrics / dimensions / data_source for a non-ecommerce
          domain (the prior hardcoding made bank/supply_chain DSL fail
          validation and triggered the validate<->correct_dsl infinite loop).
        """
        registry = self._registry or {}
        if self._is_ecommerce_registry(registry):
            return self._generate_ecommerce(question, data_source)
        return self._generate_registry_driven(question, data_source)

    @staticmethod
    def _is_ecommerce_registry(registry: dict) -> bool:
        data_sources = registry.get("data_sources", {}) or {}
        metrics = registry.get("metrics", {}) or {}
        # No data_sources (mock / test default / partial registry) -> original
        # ecommerce keyword behaviour. The registry-driven path needs real
        # data_sources to select from.
        if not data_sources:
            return True
        return "orders" in data_sources and "sales_amount" in metrics

    def _generate_ecommerce(self, question: str, data_source: str | None = None) -> DSL:
        ds = data_source or "orders"
        metrics = []
        dimensions = []
        filters = []
        order_by = []
        limit = 10

        q = question.lower()

        # Metrics
        if any(kw in question for kw in ["销售额", "sales", "业绩", "营收"]):
            metrics.append(Aggregation(func="sum", field="order_amount", alias="sales_amount"))
        elif any(kw in q for kw in ["gmv", "成交总额", "交易额"]):
            metrics.append(Aggregation(func="sum", field="order_amount", alias="gmv"))
        elif any(kw in question for kw in ["订单量", "订单数", "单量", "order count"]):
            metrics.append(Aggregation(func="count", field="id", alias="order_count"))
        elif any(kw in q for kw in ["客单价", "平均订单", "平均消费", "笔单价"]):
            metrics.append(Aggregation(func="avg", field="pay_amount", alias="avg_order_value"))
        elif any(kw in q for kw in ["优惠", "折扣", "让利"]):
            metrics.append(Aggregation(func="sum", field="discount_amount", alias="total_discount"))
        elif any(kw in q for kw in ["销量", "销售数量", "售出数量"]):
            metrics.append(Aggregation(func="sum", field="quantity", alias="total_quantity"))
        else:
            metrics.append(Aggregation(func="sum", field="order_amount", alias="sales_amount"))

        # Dimensions
        if "产品" in question or "product" in q:
            dimensions.append("product_name")
        if "品类" in question or "category" in q:
            dimensions.append("category")
        if "品牌" in question or "brand" in q:
            dimensions.append("brand")
        if "地区" in question or "区域" in question or "region" in q:
            dimensions.append("region")
        if "渠道" in question or "channel" in q or "销售方式" in question:
            dimensions.append("channel")
        if "客户" in question or "customer" in q or "用户" in q or "买家" in question:
            if "客户名" in question or "customer_name" in q or "名称" in question:
                dimensions.append("customer_name")
            else:
                dimensions.append("customer_type")
        if "时间" in question or "日期" in question or "date" in q:
            dimensions.append("order_date")

        if not dimensions:
            dimensions.append("product_name")

        # Helpers for value_map lookup
        dims_registry = self._registry.get("dimensions", {})

        def _map_value(dim_name: str, semantic_value: str) -> str:
            """Map semantic value to DB code via registry value_map."""
            vm = dims_registry.get(dim_name, {}).get("value_map", {})
            return vm.get(semantic_value, semantic_value)

        # Filters
        def _eq_or_ne(field: str, value: str, dim_name: str | None = None) -> Filter:
            """Emit `=` or `!=` based on whether the value is negated in the question."""
            mapped = _map_value(dim_name or field, value) if dim_name else value
            op = "!=" if _is_negated(question, value) else "="
            return Filter(field=field, operator=op, value=mapped)

        if "华东" in question:
            filters.append(_eq_or_ne("region", "华东", "region"))
        if "华南" in question:
            filters.append(_eq_or_ne("region", "华南", "region"))
        if "华北" in question:
            filters.append(_eq_or_ne("region", "华北", "region"))
        if "西南" in question:
            filters.append(_eq_or_ne("region", "西南", "region"))
        if "线上" in question:
            filters.append(_eq_or_ne("channel", "线上", "channel"))
        if "线下" in question:
            filters.append(_eq_or_ne("channel", "线下", "channel"))
        if "分销" in question:
            filters.append(_eq_or_ne("channel", "分销", "channel"))
        for cat in ("手机", "电脑", "家电", "服饰"):
            if cat in question:
                filters.append(_eq_or_ne("category", cat))
        if "新客" in question:
            filters.append(_eq_or_ne("customer_type", "新客"))
        if "老客" in question:
            filters.append(_eq_or_ne("customer_type", "老客"))
        if "VIP" in question:
            filters.append(_eq_or_ne("customer_type", "VIP"))

        # Numeric / range / comparison filters on price (Week 2 semantics).
        self._add_numeric_filters(filters, question)

        # Time expression resolution (Week 3): resolve any relative/absolute
        # time expression in the question into DSL.time_field/time_range.
        time_field = self._resolve_time_field(ds)
        time_range = None
        if time_field:
            resolved = resolve_time(question, time_field)
            if resolved is not None:
                time_range = resolved.time_range

        # Order by
        if metrics:
            order_by.append(OrderBy(field=metrics[0].alias or metrics[0].field, direction="desc"))

        # Limit
        if "top" in q or "最高" in question or "最多" in question:
            limit = 10
        elif "全部" in question or "所有" in question:
            limit = 100

        post_process = self._build_post_process(
            question=question,
            metrics=metrics,
            dimensions=dimensions,
        )
        if post_process is not None:
            # The SQL layer must return the complete grouped result; the
            # governed post-processor applies the per-group limit afterwards.
            limit = None

        return DSL(
            metrics=metrics,
            dimensions=dimensions,
            filters=filters or None,
            order_by=order_by or None,
            limit=limit,
            data_source=ds,
            time_field=time_field if time_range else None,
            time_range=time_range,
            post_process=post_process,
        )

    # ------------------------------------------------------------------
    # Registry-driven generation (non-ecommerce domains: bank / supply_chain)
    # ------------------------------------------------------------------

    @staticmethod
    def _func_of_expr(expr: str) -> str:
        """Derive the aggregation func from a registered metric expr.

        ``SUM(x)`` -> ``sum``, ``COUNT(DISTINCT x)`` -> ``count``,
        ``AVG(x)`` -> ``avg``, ``MIN/MAX`` likewise. Complex exprs
        (``SUM(CASE WHEN ...)``) still yield their outer func. Falls back to
        ``sum`` when the expr is empty / unparseable.
        """
        m = re.match(r"^\s*([A-Za-z_]+)\s*\(", expr or "")
        if not m:
            return "sum"
        fn = m.group(1).lower()
        return fn if fn in {"sum", "avg", "count", "min", "max"} else "sum"

    @staticmethod
    def _make_aggregation(alias: str, metrics_cfg: dict) -> Aggregation:
        """Build an Aggregation whose alias is a registered metric.

        ``field`` is the inner column of a simple expr (``SUM(acct_bal)`` ->
        ``acct_bal``); for complex exprs (``CASE WHEN``) it falls back to the
        alias. The SQLBuilder treats the registered ``expr`` (looked up by
        alias) as authoritative, so ``field`` is only a fallback.
        """
        cfg = metrics_cfg.get(alias, {}) or {}
        expr = cfg.get("expr") or ""
        func = RuleBasedDSLGenerator._func_of_expr(expr)
        field = alias
        m = re.match(
            r"^[A-Za-z_]+\(\s*(?:DISTINCT\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\)$",
            expr, re.IGNORECASE,
        )
        if m:
            field = m.group(1)
        return Aggregation(func=func, field=field, alias=alias)

    @staticmethod
    def _desc_clean(desc: str) -> str:
        """Strip parentheticals from a registry description for matching."""
        return re.sub(r"[（(].*?[)）]", "", desc or "").strip()

    @classmethod
    def _score_terms(cls, question: str, desc: str) -> int:
        """Score overlap between question and a description's n-gram terms.

        Exact description substring scores highest (len*3); individual 3-gram
        and 2-gram overlaps add len each. Longer matched terms outweigh
        shorter ones so a specific match beats a generic one.
        """
        q = question
        desc_clean = cls._desc_clean(desc)
        score = 0
        if desc_clean and desc_clean in q:
            score += len(desc_clean) * 3
        seen: set[str] = set()
        for n in (3, 2):
            for i in range(len(desc_clean) - n + 1):
                term = desc_clean[i:i + n]
                if len(term) >= 2 and term not in seen:
                    seen.add(term)
                    if term in q:
                        score += len(term)
        return score

    def _score_metric(self, question: str, alias: str, cfg: dict) -> int:
        desc = (cfg.get("description") or "").strip()
        expr = cfg.get("expr") or ""
        q = question
        score = self._score_terms(q, desc)
        if alias and alias in q:
            score += len(alias)
        func = self._func_of_expr(expr)
        # Func hints disambiguate metrics with overlapping description terms.
        if func == "avg" and ("平均" in q or "avg" in q.lower()):
            score += 4
        if func == "min" and ("最低" in q or "最少" in q):
            score += 4
        if func == "max" and ("最高" in q or "最多" in q):
            score += 4
        if func == "count" and "笔数" in q:
            score += 3
        # Amount/price semantic boost: when the question asks for a monetary
        # amount, prefer metrics whose description carries an amount keyword.
        if any(a in q for a in ("金额", "余额", "成本")) and any(
            a in desc for a in ("金额", "余额", "成本", "持有")
        ):
            score += 6
        return score

    def _score_dim(self, question: str, dim: str, cfg: dict) -> int:
        desc = (cfg.get("description") or "").strip()
        score = self._score_terms(question, desc)
        if dim and dim in question:
            score += len(dim)
        return score

    def _choose_data_source(
        self, question: str, data_sources: dict, metrics_cfg: dict, dims_cfg: dict,
    ) -> str:
        """Pick the data_source whose metrics/dimensions best match the question.

        Falls back to the first data_source (registry-defined default) when no
        keyword matches — never to ecommerce's ``orders``.
        """
        if not data_sources:
            return "orders"
        best_ds: str | None = None
        best_score = 0
        for name, cfg in data_sources.items():
            score = 0
            for m in (cfg.get("metrics") or []):
                score += self._score_metric(question, m, metrics_cfg.get(m, {}) or {})
            for d in (cfg.get("dimensions") or []):
                score += self._score_dim(question, d, dims_cfg.get(d, {}) or {})
            if score > best_score:
                best_score = score
                best_ds = name
        if best_ds is not None and best_score > 0:
            return best_ds
        return next(iter(data_sources))

    def _choose_metrics(
        self, question: str, ds_metric_names: list[str], metrics_cfg: dict,
    ) -> list[Aggregation]:
        scored = [
            (self._score_metric(question, name, metrics_cfg.get(name, {}) or {}), name)
            for name in ds_metric_names
        ]
        scored = [(s, n) for s, n in scored if s > 0]
        if not scored:
            # Default: first metric of the data_source (registry-defined,
            # never an ecommerce metric).
            return [self._make_aggregation(ds_metric_names[0], metrics_cfg)] if ds_metric_names else []
        # Stable order: by score desc, then registry order.
        order_index = {n: i for i, n in enumerate(ds_metric_names)}
        scored.sort(key=lambda x: (-x[0], order_index[x[1]]))
        chosen = [scored[0][1]]
        # Multi-metric when the question explicitly joins two metrics with
        # 和/与/, and the second-best scores reasonably close to the top.
        if len(scored) >= 2 and any(sep in question for sep in ("和", "与", "，", ",")):
            if scored[1][0] * 5 >= scored[0][0] * 2:
                chosen.append(scored[1][1])
        return [self._make_aggregation(n, metrics_cfg) for n in chosen]

    def _reachable_dims(
        self, ds_cfg: dict, data_sources: dict,
    ) -> list[str]:
        """Dimensions usable from a data_source: its own dims plus dims of any
        data_source whose physical table is the primary table or a declared
        join target (mirror of DSLValidator._dim_reachable_via_joins)."""
        reachable_tables: set[str] = {ds_cfg.get("table", "")}
        joins = ds_cfg.get("joins", {}) or {}
        if isinstance(joins, dict):
            reachable_tables.update(joins.keys())
        reachable_tables.discard("")
        seen: list[str] = []
        for cfg in data_sources.values():
            if cfg.get("table") in reachable_tables:
                for d in (cfg.get("dimensions") or []):
                    if d not in seen:
                        seen.append(d)
        return seen

    def _choose_dimensions(
        self, question: str, ds_cfg: dict, data_sources: dict, dims_cfg: dict,
    ) -> list[str]:
        """Pick the grouping dimension for the question.

        Pure aggregate questions (``查询客户数量`` / ``总库存量``) yield no
        dimensions. Grouping (``各账户类型`` / ``按供应商``) or ranking
        (``交易笔数最多的客户``) questions yield exactly the best-matching
        dimension — not every dimension whose description shares a noun with
        the metric (that would wrongly group ``查询客户数量`` by customer_*).
        Candidates include join-reachable dimensions (e.g. ``customer_name``
        from a joined customer table). Display-name dimensions (alias
        ``*_name`` / description 含 名称/姓名) win ties; the noun following a
        ranking cue's ``的`` (``最多的客户`` -> ``客户``) gets an extra boost.
        """
        group_cue = any(c in question for c in ("各", "每个", "每种", "按"))
        # "前" alone is too broad ("提前期" contains it); require 前+digit or
        # the english "top" marker.
        ranking_cue = any(k in question for k in ("最多", "最高", "最低", "最少")) or bool(
            re.search(r"前\d", question)
        ) or "top" in question.lower()
        candidates = self._reachable_dims(ds_cfg, data_sources)
        if not (group_cue or ranking_cue) or not candidates:
            return []
        # Noun targeted by a ranking cue: substring after the last "的".
        rank_target = ""
        if ranking_cue and "的" in question:
            rank_target = question.rsplit("的", 1)[-1].strip()
        order_index = {d: i for i, d in enumerate(candidates)}
        scored: list[tuple[int, str]] = []
        for d in candidates:
            cfg = dims_cfg.get(d, {}) or {}
            s = self._score_dim(question, d, cfg)
            if s > 0 and (
                d.endswith("_name")
                or "名称" in (cfg.get("description") or "")
                or "姓名" in (cfg.get("description") or "")
            ):
                s += 1
            if rank_target and rank_target in (cfg.get("description") or ""):
                s += 3
            scored.append((s, d))
        scored.sort(key=lambda x: (-x[0], order_index[x[1]]))
        if scored and scored[0][0] > 0:
            return [scored[0][1]]
        # Grouping cue present but no dim matched — default to the first
        # direct dim of the data_source (registry-defined).
        direct = ds_cfg.get("dimensions") or []
        return [direct[0]] if direct else []

    def _build_dimension_filters(
        self, question: str, ds_dim_names: list[str], dims_cfg: dict,
    ) -> list[Filter]:
        """Emit value_map filters for any data_source dimension whose mapped
        value appears in the question (e.g. 华东 -> region_name='HD')."""
        filters: list[Filter] = []
        for d in ds_dim_names:
            vm = (dims_cfg.get(d, {}) or {}).get("value_map") or {}
            for semantic_value, code in vm.items():
                if semantic_value in question:
                    op = "!=" if _is_negated(question, semantic_value) else "="
                    filters.append(Filter(field=d, operator=op, value=code))
        return filters

    def _generate_registry_driven(
        self, question: str, data_source: str | None = None,
    ) -> DSL:
        """Generate a registry-valid DSL for a non-ecommerce domain.

        Every metric alias / dimension / data_source is selected from the
        domain's registry, so the DSL passes validation and executes against
        the domain's schema (no ecommerce hardcoding).
        """
        registry = self._registry or {}
        data_sources = registry.get("data_sources", {}) or {}
        metrics_cfg = registry.get("metrics", {}) or {}
        dims_cfg = registry.get("dimensions", {}) or {}

        ds_name = self._choose_data_source(question, data_sources, metrics_cfg, dims_cfg)
        ds_cfg = data_sources.get(ds_name, {}) or {}
        ds_metric_names = ds_cfg.get("metrics", []) or []
        ds_dim_names = ds_cfg.get("dimensions", []) or []

        metrics = self._choose_metrics(question, ds_metric_names, metrics_cfg)
        dimensions = self._choose_dimensions(question, ds_cfg, data_sources, dims_cfg)
        filters = self._build_dimension_filters(question, ds_dim_names, dims_cfg)

        # Time range from the data_source's declared time_field.
        time_field = ds_cfg.get("time_field") or self._resolve_time_field(ds_name)
        time_range = None
        if time_field:
            resolved = resolve_time(question, time_field)
            if resolved is not None:
                time_range = resolved.time_range

        # Order by only when the question asks for ranking.
        order_by: list[OrderBy] = []
        if metrics and any(k in question for k in ("最多", "最高", "最低", "最少", "前", "top")):
            alias = metrics[0].alias or metrics[0].field
            direction = "asc" if any(k in question for k in ("最低", "最少", "后")) else "desc"
            order_by.append(OrderBy(field=alias, direction=direction))

        limit = 100 if ("全部" in question or "所有" in question) else 10

        post_process = self._build_post_process(question=question, metrics=metrics, dimensions=dimensions)

        return DSL(
            metrics=metrics or None,
            dimensions=dimensions or None,
            filters=filters or None,
            order_by=order_by or None,
            limit=limit,
            data_source=ds_name,
            time_field=time_field if time_range else None,
            time_range=time_range,
            post_process=post_process,
        )

    def _resolve_time_field(self, data_source: str) -> str | None:
        """Find the date-typed time dimension for a data source.

        Returns the first dimension declared under ``data_source`` whose
        ``type == "date"`` (e.g. ``order_date`` for ``orders``), falling back
        to a scan of all registry dimensions. Mirrors
        ``SemanticConfig.get_time_field`` but works off the raw registry dict
        available to the rule-based generator.
        """
        dims_registry = self._registry.get("dimensions", {})
        sources = self._registry.get("data_sources", {})
        for dim_id in sources.get(data_source, {}).get("dimensions", []):
            if dims_registry.get(dim_id, {}).get("type") == "date":
                return dim_id
        for dim_id, cfg in dims_registry.items():
            if isinstance(cfg, dict) and cfg.get("type") == "date":
                return dim_id
        return None

    @staticmethod
    def _build_post_process(
        question: str,
        metrics: list[Aggregation],
        dimensions: list[str],
    ) -> PostProcess | None:
        if not metrics:
            return None
        metric = metrics[0].alias or metrics[0].field

        if any(keyword in question for keyword in ("占比", "比例", "贡献度")):
            return PostProcess(
                type="proportion",
                metric=metric,
                output_field=f"{metric}_proportion",
            )

        grouped_rank = (
            len(dimensions) >= 2
            and any(marker in question for marker in ("各", "每个", "每种"))
            and any(marker in question for marker in ("最高", "最低", "前", "后"))
        )
        if grouped_rank:
            match = re.search(r"(?:前|最高的?|最低的?|后)\s*(\d+)", question)
            top_n = int(match.group(1)) if match else 1
            direction = "asc" if any(k in question for k in ("最低", "最少", "后")) else "desc"
            group_candidates = (
                ("品类", "category"),
                ("地区", "region"),
                ("区域", "region"),
                ("渠道", "channel"),
                ("品牌", "brand"),
                ("客户", "customer_type"),
            )
            group_dimension = next(
                (
                    dim
                    for keyword, dim in group_candidates
                    if any(
                        marker in question
                        for marker in (
                            f"各{keyword}",
                            f"每个{keyword}",
                            f"每种{keyword}",
                        )
                    )
                    and dim in dimensions
                ),
                dimensions[0],
            )
            return PostProcess(
                type="group_top_n",
                metric=metric,
                group_by=[group_dimension],
                top_n=top_n,
                direction=direction,
            )
        return None

    @staticmethod
    def _add_numeric_filters(filters: list, question: str) -> None:
        """Detect numeric comparison / range / negation on price.

        Supports:
        - range: "价格在5000到20000之间" / "介于5000和20000之间" → between [5000, 20000]
        - comparison: "价格大于5000"/"超过5000"/">=8000"/"小于3000" → > / >= / <
        Comparison is skipped when a range was matched (range takes precedence).
        """
        # Range: between X and Y  (X到Y之间 / 介于X和Y之间)
        range_match = re.search(
            r"(?:价格|单价)?[在介]?于?\s*(\d+(?:\.\d+)?)\s*(?:到|和|至|-|~)\s*(\d+(?:\.\d+)?)\s*(?:元)?之间",
            question,
        )
        if range_match:
            lo, hi = float(range_match.group(1)), float(range_match.group(2))
            lo, hi = (lo, hi) if lo <= hi else (hi, lo)
            filters.append(Filter(field="price", operator="between", value=[lo, hi]))
            return

        # Comparison: look for an explicit number near a comparison cue.
        comp_match = re.search(
            r"价格(?:大于等于|大于|超过|高于|不少于|不低于|小于等于|小于|低于|不多于|不高于|≥|<=|>=|>|<)\s*(\d+(?:\.\d+)?)"
            r"|大于等于\s*(\d+(?:\.\d+)?)|大于\s*(\d+(?:\.\d+)?)|超过\s*(\d+(?:\.\d+)?)"
            r"|小于等于\s*(\d+(?:\.\d+)?)|小于\s*(\d+(?:\.\d+)?)",
            question,
        )
        if not comp_match:
            return

        # Determine operator + value from whichever group matched.
        token = comp_match.group(0)
        value = float(next(g for g in comp_match.groups() if g is not None))
        if any(c in token for c in ("大于等于", "不少于", "不低于", "≥", ">=")):
            op = ">="
        elif any(c in token for c in ("小于等于", "不多于", "不高于", "<=")):
            op = "<="
        elif any(c in token for c in ("大于", "超过", "高于", ">")):
            op = ">"
        elif any(c in token for c in ("小于", "低于", "<")):
            op = "<"
        else:
            return
        filters.append(Filter(field="price", operator=op, value=value))


class MaxRetryExceeded(Exception):
    """Raised when all retry attempts are exhausted."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"DSL generation failed after retries. Errors: {'; '.join(errors)}")


class RetryChain(DSLGenerator):
    """Wraps a DSL generator with error feedback + retry logic.

    On failure, captures the error, feeds it back to the generator,
    and retries up to max_retries times.
    """

    def __init__(
        self,
        generator: DSLGenerator,
        validator: Callable[[DSL], None] | None = None,
        max_retries: int = 3,
    ):
        self._generator = generator
        self._validator = validator
        self._max_retries = max_retries
        self._errors: list[str] = []

    def generate(self, question: str, data_source: str | None = None) -> DSL:
        """Generate DSL with retry on validation failures."""
        self._errors = []

        for attempt in range(self._max_retries):
            try:
                # Build prompt with error feedback for subsequent attempts
                prompt = self._build_prompt(question)
                dsl = self._generator.generate(prompt, data_source)

                # Validate if validator provided
                if self._validator:
                    self._validator(dsl)

                return dsl

            except (ValidationError, ValueError, KeyError) as e:
                error_msg = str(e)
                self._errors.append(error_msg)
                if attempt < self._max_retries - 1:
                    continue
                raise MaxRetryExceeded(self._errors)

        # Should not reach here, but just in case
        raise MaxRetryExceeded(self._errors)

    def _build_prompt(self, question: str) -> str:
        """Build prompt with error feedback from previous attempts."""
        if not self._errors:
            return question

        feedback = "\n".join(
            f"Attempt {i + 1} failed: {err}" for i, err in enumerate(self._errors)
        )
        return (
            f"{question}\n\n"
            f"Previous attempts failed:\n{feedback}\n\n"
            f"Please fix the errors and generate a correct DSL."
        )
