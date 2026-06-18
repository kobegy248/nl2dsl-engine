"""Normalizer — structural DSL normalization without semantic config."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NormalizerLog:
    """Record of normalization actions taken."""

    actions: list[str] = field(default_factory=list)

    def add(self, action: str) -> None:
        self.actions.append(action)


class Normalizer:
    """Structural normalizer for raw DSL dicts.

    Does NOT access semantic config. Only enforces structural
    correctness: defaults, type coercion, dedup, format normalization.
    """

    DEFAULT_LIMIT = 100

    def normalize(self, raw_dsl: dict) -> tuple[dict, NormalizerLog]:
        """Normalize a raw DSL dict.

        Returns:
            (normalized_dsl_dict, NormalizerLog)
        """
        import copy

        dsl = copy.deepcopy(raw_dsl)
        log = NormalizerLog()

        # 1. Ensure top-level fields exist with defaults
        defaults = {
            "metrics": None,
            "dimensions": None,
            "filters": None,
            "having": None,
            "order_by": None,
            "limit": self.DEFAULT_LIMIT,
            "offset": 0,
            "data_source": "",
            "time_field": None,
            "time_range": None,
            "joins": None,
        }
        for key, default in defaults.items():
            if key not in dsl:
                dsl[key] = default
                log.add(f"Added missing field '{key}' = {default!r}")

        # 2. Type coercion
        dsl, coercion_log = self._coerce_types(dsl)
        log.actions.extend(coercion_log)

        # 3. Filter structure normalization
        if dsl.get("filters") is not None:
            dsl["filters"] = self._normalize_filters(dsl["filters"], log)

        # 4. Dedup metrics by (func, field) pair
        metrics = dsl.get("metrics")
        if isinstance(metrics, list) and len(metrics) > 0:
            seen = set()
            deduped = []
            for m in metrics:
                key = (m.get("func", ""), m.get("field", ""))
                if key not in seen:
                    seen.add(key)
                    deduped.append(m)
            if len(deduped) < len(metrics):
                log.add(f"Deduped metrics: {len(metrics)} -> {len(deduped)}")
                dsl["metrics"] = deduped

        return dsl, log

    def _coerce_types(self, dsl: dict) -> tuple[dict, list[str]]:
        """Coerce field types to their expected formats."""
        log: list[str] = []

        # Coerce limit to int
        if "limit" in dsl and dsl["limit"] is not None:
            try:
                dsl["limit"] = int(dsl["limit"])
            except (ValueError, TypeError):
                log.append(f"Could not coerce limit={dsl['limit']!r} to int, using default")
                dsl["limit"] = self.DEFAULT_LIMIT

        # Coerce offset to int
        if "offset" in dsl and dsl["offset"] is not None:
            try:
                dsl["offset"] = int(dsl["offset"])
            except (ValueError, TypeError):
                dsl["offset"] = 0
                log.append("Coerced invalid offset to 0")

        # Coerce empty data_source
        if dsl.get("data_source") is None:
            dsl["data_source"] = ""
            log.append("Coerced null data_source to empty string")

        # Coerce empty string lists to None
        for field in ("metrics", "dimensions", "joins", "order_by"):
            val = dsl.get(field)
            if isinstance(val, list) and len(val) == 0:
                dsl[field] = None
                log.append(f"Coerced empty {field} list to None")

        return dsl, log

    def _normalize_filters(self, filters, log: NormalizerLog) -> list[dict]:
        """Accept multiple filter representations, return unified list of dicts."""
        if filters is None:
            return None

        # Already a list of filter dicts
        if isinstance(filters, list):
            normalized = []
            for f in filters:
                if isinstance(f, dict):
                    normalized.append(self._normalize_single_filter(f))
            return normalized if normalized else None

        # Tree format: {"op": "and", "children": [...]}
        if isinstance(filters, dict):
            if "op" in filters and "children" in filters:
                log.add("Normalized filter tree to flat list (recursive)")
                return self._flatten_filter_tree(filters, log)
            # Single filter dict
            return [self._normalize_single_filter(filters)]

        return None

    def _normalize_single_filter(self, f: dict) -> dict:
        """Ensure a single filter dict has required keys."""
        return {
            "field": f.get("field", ""),
            "operator": f.get("operator", "="),
            "value": f.get("value"),
        }

    def _flatten_filter_tree(self, node: dict, log: NormalizerLog) -> list[dict]:
        """Flatten a filter tree into a list. For non-trivial trees, this is lossy
        (loses AND/OR structure), so we log a warning.

        ``not`` nodes with a single leaf child are preserved by inverting the
        leaf's operator (e.g. ``not{category=手机}`` → ``category != 手机``),
        so negation semantics are not silently dropped. ``not`` over a nested
        and/or subtree, or over ``in``/``between``/``like``/``is_null`` (which
        have no single-leaf negation), cannot be losslessly flattened and only
        a warning is logged.
        """
        results = []
        op = node.get("op", "and")
        children = node.get("children", [])

        if op == "not" and len(children) == 1 and isinstance(children[0], dict):
            child = children[0]
            if not ("op" in child and "children" in child):
                inverted = self._invert_leaf(child)
                if inverted is not None:
                    results.append(self._normalize_single_filter(inverted))
                    return results
                # Cannot express negation as a single leaf — fall through to
                # append the original leaf and warn (do not silently drop it).
                log.add("Warning: 'not' over non-invertible operator — negation may be lost")
                results.append(self._normalize_single_filter(child))
                return results
            # not over a nested and/or subtree — cannot invert losslessly
            log.add("Warning: 'not' over nested subtree — negation may be lost")

        for child in children:
            if isinstance(child, dict):
                if "op" in child and "children" in child:
                    # Nested tree
                    results.extend(self._flatten_filter_tree(child, log))
                else:
                    results.append(self._normalize_single_filter(child))

        if op == "or":
            log.add("Warning: flattened OR filter tree — logical structure may be lost")
        return results

    # Operators that can be inverted to express negation as a single leaf.
    _OPPOSITE = {
        "=": "!=",
        "!=": "=",
        ">": "<=",
        "<": ">=",
        ">=": "<",
        "<=": ">",
    }

    def _invert_leaf(self, leaf: dict) -> dict | None:
        """Return a single-leaf negation of ``leaf``, or None if not invertible."""
        operator = leaf.get("operator")
        if operator in self._OPPOSITE:
            inverted = self._normalize_single_filter(leaf)
            inverted["operator"] = self._OPPOSITE[operator]
            return inverted
        return None

    def _ensure_aliases(self, dsl: dict, log: NormalizerLog) -> dict:
        """Generate default aliases for metrics that lack them."""
        metrics = dsl.get("metrics")
        if not metrics:
            return dsl

        for i, m in enumerate(metrics):
            if isinstance(m, dict) and not m.get("alias"):
                func = m.get("func", "").upper()
                field = m.get("field", "unknown")
                alias = f"{func.lower()}_{field}" if func else field
                m["alias"] = alias
                log.add(f"Generated alias '{alias}' for metrics[{i}]")

        return dsl
