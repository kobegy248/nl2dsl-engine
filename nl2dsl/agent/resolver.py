"""EntityResolver: deterministic entity-to-service mapping.

Maps natural language entities (metrics, dimensions, dimension values) to
governance service identifiers by scanning the rule tables held in a
``SemanticRegistry``.  No LLM is involved — the same input always produces
the same output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from nl2dsl.semantic.registry import SemanticRegistry


@dataclass
class ResolvedEntity:
    """Result of resolving entities from a natural language question."""

    metric_services: list[str] = field(default_factory=list)
    dimension_services: list[tuple[str, str | None]] = field(default_factory=list)
    data_source: str | None = None


class EntityResolver:
    """Deterministic resolver that maps NL entities to governance services.

    The resolver scans the registry's metrics, dimensions, and data sources
    looking for matches by description, alias, or value_map entry.  Matches
    are exact (case-sensitive for Chinese, case-insensitive for ASCII).
    """

    def __init__(self, registry: SemanticRegistry) -> None:
        self._registry = registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_metric(self, text: str) -> str | None:
        """Find a metric service name whose description or alias matches *text*.

        Returns the metric key (e.g. ``"sales_amount"``) or ``None``.
        """
        for name, meta in self._registry.metrics.items():
            if self._match_text(text, meta):
                return name
        return None

    def resolve_dimension(self, text: str) -> str | None:
        """Find a dimension service name whose description or alias matches *text*.

        Returns the dimension key (e.g. ``"region"``) or ``None``.
        """
        for name, meta in self._registry.dimensions.items():
            if self._match_text(text, meta):
                return name
        return None

    def resolve_dimension_value(self, text: str) -> tuple[str, str] | None:
        """Find a dimension + encoded value that matches *text*.

        Scans every dimension's ``value_map`` for an exact key match.
        Returns ``(dimension_name, encoded_value)`` or ``None``.
        """
        for dim_name, meta in self._registry.dimensions.items():
            value_map = meta.get("value_map", {})
            if text in value_map:
                return dim_name, value_map[text]
        return None

    def resolve(self, question: str) -> ResolvedEntity:
        """Resolve all entities present in *question*.

        The method tokenises the question on whitespace and punctuation, then
        tries each token (and every consecutive pair of tokens) against the
        metric, dimension, and dimension-value tables.
        """
        tokens = self._tokenise(question)
        metrics: set[str] = set()
        dimensions: set[tuple[str, str | None]] = set()

        # Try single tokens and consecutive pairs (covers multi-word descriptions)
        candidates: list[str] = []
        for i, token in enumerate(tokens):
            candidates.append(token)
            if i + 1 < len(tokens):
                candidates.append(f"{token}{tokens[i + 1]}")

        for candidate in candidates:
            metric = self.resolve_metric(candidate)
            if metric:
                metrics.add(metric)

            dim = self.resolve_dimension(candidate)
            if dim:
                dimensions.add((dim, None))

            dim_val = self.resolve_dimension_value(candidate)
            if dim_val:
                dimensions.add(dim_val)

        # Determine the most likely data source from resolved metrics/dimensions
        data_source = self._infer_data_source(metrics, {d for d, _ in dimensions})

        return ResolvedEntity(
            metric_services=sorted(metrics),
            dimension_services=sorted(dimensions, key=lambda x: x[0]),
            data_source=data_source,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _match_text(text: str, meta: dict) -> bool:
        """Return True if *text* matches the metric/dimension metadata."""
        # Exact match on description
        description = meta.get("description", "")
        if description and text == description:
            return True

        # Exact match on any alias
        aliases = meta.get("aliases", [])
        if text in aliases:
            return True

        # Case-insensitive match for ASCII text
        if text.isascii():
            lower_text = text.lower()
            if description and lower_text == description.lower():
                return True
            if any(lower_text == alias.lower() for alias in aliases):
                return True

        return False

    @staticmethod
    def _tokenise(text: str) -> list[str]:
        """Split text on whitespace and common punctuation.

        Chinese text has no word boundaries, so we also generate every
        consecutive substring of Chinese characters as a candidate token.
        """
        # Split on ASCII punctuation/whitespace
        raw_tokens = [t for t in re.split(r"[\s,;:!?。，；：！？]+", text) if t]

        candidates: list[str] = []
        for token in raw_tokens:
            candidates.append(token)
            # If the token is all Chinese, also emit every substring so that
            # embedded metric/dimension descriptions can be matched.
            if token and all("一" <= ch <= "鿿" for ch in token):
                n = len(token)
                for length in range(2, n + 1):
                    for start in range(0, n - length + 1):
                        candidates.append(token[start : start + length])

        return candidates

    def _infer_data_source(
        self,
        metrics: set[str],
        dimensions: set[str],
    ) -> str | None:
        """Pick the data source that best covers the resolved metrics/dims."""
        best_source: str | None = None
        best_score = -1

        for name, meta in self._registry.data_sources.items():
            ds_metrics = set(meta.get("metrics", []))
            ds_dimensions = set(meta.get("dimensions", []))

            score = 0
            if metrics:
                score += len(metrics & ds_metrics)
            if dimensions:
                score += len(dimensions & ds_dimensions)

            if score > best_score:
                best_score = score
                best_source = name

        # Only return a data source if at least one metric or dimension matched
        return best_source if best_score > 0 else None
