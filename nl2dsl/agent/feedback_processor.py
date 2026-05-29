"""Feedback processor — periodically consumes user feedback and extracts
high-frequency correction patterns.

MVP behaviour
-------------
* Reads feedback records from a :class:`FeedbackCollector`.
* Counts how often metric aliases and filter field/value pairs are corrected.
* Returns patterns whose frequency is >= ``MIN_CORRECTION_FREQUENCY``.
* Logs discovered patterns (registry file mutation is reserved for a future
  iteration).
* Tracks processed ``query_id``\ s so the same record is never analysed twice.
* Provides ``run_periodically`` for background execution.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import TYPE_CHECKING

from nl2dsl.utils.logger import get_logger

if TYPE_CHECKING:
    from nl2dsl.feedback.collector import FeedbackCollector

MIN_CORRECTION_FREQUENCY: int = 3
"""Default minimum occurrence count for a correction pattern to be reported."""

logger = get_logger("agent.feedback_processor")


def extract_correction_patterns(
    records: list[dict],
    *,
    min_frequency: int = MIN_CORRECTION_FREQUENCY,
) -> list[dict]:
    """Extract high-frequency correction patterns from feedback records.

    Two categories are tracked:

    * **metric_alias** — values of ``corrected_dsl.metrics[].alias``.
    * **filter** — ``{field}={value}`` strings built from
      ``corrected_dsl.filters[].field`` and ``filters[].value`` (or
      ``filters[].operator`` when ``value`` is absent).

    Only patterns whose count is *>=* ``min_frequency`` are returned.

    Parameters
    ----------
    records:
        Raw feedback records (as returned by
        :meth:`FeedbackCollector.list_feedback`).
    min_frequency:
        Threshold count.  Defaults to :data:`MIN_CORRECTION_FREQUENCY`.

    Returns
    -------
    list[dict]
        Each dict has keys ``correction_type``, ``corrected_value``,
        ``frequency``.
    """
    metric_counter: Counter[str] = Counter()
    filter_counter: Counter[str] = Counter()

    for record in records:
        corrected_dsl = record.get("corrected_dsl")
        if not corrected_dsl or not isinstance(corrected_dsl, dict):
            continue

        # Metric aliases
        metrics = corrected_dsl.get("metrics")
        if isinstance(metrics, list):
            for metric in metrics:
                if isinstance(metric, dict):
                    alias = metric.get("alias")
                    if alias is not None:
                        metric_counter[alias] += 1

        # Filters
        filters = corrected_dsl.get("filters")
        if isinstance(filters, list):
            for filt in filters:
                if isinstance(filt, dict):
                    field = filt.get("field")
                    value = filt.get("value")
                    operator = filt.get("operator", "")
                    if field is not None:
                        if value is not None:
                            key = f"{field}={value}"
                        else:
                            key = f"{field}={operator}"
                        filter_counter[key] += 1

    patterns: list[dict] = []
    for alias, count in metric_counter.items():
        if count >= min_frequency:
            patterns.append(
                {
                    "correction_type": "metric_alias",
                    "corrected_value": alias,
                    "frequency": count,
                }
            )
    for filt_key, count in filter_counter.items():
        if count >= min_frequency:
            patterns.append(
                {
                    "correction_type": "filter",
                    "corrected_value": filt_key,
                    "frequency": count,
                }
            )

    return patterns


class FeedbackProcessor:
    """Periodically processes user feedback to discover correction patterns.

    Parameters
    ----------
    collector:
        A :class:`FeedbackCollector` instance that owns the feedback store.
    registry_dict:
        In-memory registry mapping (e.g. loaded from ``terms.yaml``).
        In the MVP this dict is only read / logged; it is **not** mutated.
    """

    def __init__(self, collector: FeedbackCollector, registry_dict: dict) -> None:
        self._collector = collector
        self._registry = registry_dict
        self._processed_ids: set[str] = set()

    def process_once(self) -> list[dict]:
        """Read new feedback, extract patterns, and update term weights.

        Records whose ``query_id`` has already been processed are skipped.

        Returns
        -------
        list[dict]
            The list of newly-discovered high-frequency patterns.
        """
        records = self._collector.list_feedback()
        new_records = [
            r for r in records if r.get("query_id") not in self._processed_ids
        ]

        if not new_records:
            logger.debug("No new feedback records to process.")
            return []

        for record in new_records:
            qid = record.get("query_id")
            if qid is not None:
                self._processed_ids.add(qid)

        patterns = extract_correction_patterns(new_records)
        if patterns:
            logger.info(
                "Extracted %d correction pattern(s) from %d new record(s).",
                len(patterns),
                len(new_records),
            )
            self._update_term_weights(patterns)
        else:
            logger.debug(
                "No high-frequency patterns found in %d new record(s).",
                len(new_records),
            )

        return patterns

    def _update_term_weights(self, patterns: list[dict]) -> None:
        """Log discovered patterns.

        .. note::
            This is an MVP stub.  A future iteration will write updated
            weights back to ``terms.yaml``.
        """
        for pattern in patterns:
            logger.info(
                "Pattern: type=%s value=%s frequency=%d",
                pattern["correction_type"],
                pattern["corrected_value"],
                pattern["frequency"],
            )

    async def run_periodically(self, interval_seconds: float) -> None:
        """Run :meth:`process_once` in an infinite async loop.

        The loop can be cancelled with ``task.cancel()``.

        Parameters
        ----------
        interval_seconds:
            Seconds to sleep between processing rounds.
        """
        while True:
            try:
                self.process_once()
            except Exception:
                logger.exception("Error during feedback processing")
            await asyncio.sleep(interval_seconds)
