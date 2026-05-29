"""Unit tests for nl2dsl.agent.feedback_processor."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nl2dsl.agent.feedback_processor import (
    FeedbackProcessor,
    MIN_CORRECTION_FREQUENCY,
    extract_correction_patterns,
)
from nl2dsl.feedback.collector import FeedbackCollector


# ---------------------------------------------------------------------------
# extract_correction_patterns
# ---------------------------------------------------------------------------


def make_record(query_id: str, corrected_dsl: dict | None = None) -> dict:
    return {
        "query_id": query_id,
        "user_id": "u1",
        "corrected_dsl": corrected_dsl,
        "comment": "",
    }


def test_extract_empty_records():
    patterns = extract_correction_patterns([])
    assert patterns == []


def test_extract_no_corrected_dsl():
    records = [
        make_record("q1", None),
        make_record("q2", None),
    ]
    patterns = extract_correction_patterns(records)
    assert patterns == []


def test_extract_metric_alias_corrections():
    records = [
        make_record("q1", {"metrics": [{"alias": "revenue"}]}),
        make_record("q2", {"metrics": [{"alias": "revenue"}]}),
        make_record("q3", {"metrics": [{"alias": "revenue"}]}),
        make_record("q4", {"metrics": [{"alias": "sales"}]}),
        make_record("q5", {"metrics": [{"alias": "sales"}]}),
    ]
    patterns = extract_correction_patterns(records)
    # revenue appears 3 times (>= MIN_CORRECTION_FREQUENCY=3)
    # sales appears 2 times (< threshold)
    assert len(patterns) == 1
    assert patterns[0]["correction_type"] == "metric_alias"
    assert patterns[0]["corrected_value"] == "revenue"
    assert patterns[0]["frequency"] == 3


def test_extract_filter_corrections():
    records = [
        make_record(
            "q1",
            {"filters": [{"field": "region", "operator": "=", "value": "US"}]},
        ),
        make_record(
            "q2",
            {"filters": [{"field": "region", "operator": "=", "value": "US"}]},
        ),
        make_record(
            "q3",
            {"filters": [{"field": "region", "operator": "=", "value": "US"}]},
        ),
        make_record(
            "q4",
            {"filters": [{"field": "status", "operator": "=", "value": "active"}]},
        ),
    ]
    patterns = extract_correction_patterns(records)
    # "region=US" appears 3 times
    assert len(patterns) == 1
    assert patterns[0]["correction_type"] == "filter"
    assert patterns[0]["corrected_value"] == "region=US"
    assert patterns[0]["frequency"] == 3


def test_extract_both_types():
    records = [
        make_record("q1", {"metrics": [{"alias": "revenue"}]}),
        make_record("q2", {"metrics": [{"alias": "revenue"}]}),
        make_record("q3", {"metrics": [{"alias": "revenue"}]}),
        make_record(
            "q4",
            {"filters": [{"field": "region", "operator": "=", "value": "US"}]},
        ),
        make_record(
            "q5",
            {"filters": [{"field": "region", "operator": "=", "value": "US"}]},
        ),
        make_record(
            "q6",
            {"filters": [{"field": "region", "operator": "=", "value": "US"}]},
        ),
    ]
    patterns = extract_correction_patterns(records)
    assert len(patterns) == 2
    types = {p["correction_type"] for p in patterns}
    assert types == {"metric_alias", "filter"}


def test_extract_multiple_metrics_in_one_record():
    records = [
        make_record(
            "q1",
            {"metrics": [{"alias": "revenue"}, {"alias": "profit"}]},
        ),
        make_record(
            "q2",
            {"metrics": [{"alias": "revenue"}, {"alias": "profit"}]},
        ),
        make_record(
            "q3",
            {"metrics": [{"alias": "revenue"}, {"alias": "profit"}]},
        ),
    ]
    patterns = extract_correction_patterns(records)
    assert len(patterns) == 2
    values = {p["corrected_value"] for p in patterns}
    assert values == {"revenue", "profit"}
    for p in patterns:
        assert p["frequency"] == 3


def test_extract_multiple_filters_in_one_record():
    records = [
        make_record(
            "q1",
            {
                "filters": [
                    {"field": "region", "operator": "=", "value": "US"},
                    {"field": "status", "operator": "=", "value": "active"},
                ]
            },
        ),
        make_record(
            "q2",
            {
                "filters": [
                    {"field": "region", "operator": "=", "value": "US"},
                    {"field": "status", "operator": "=", "value": "active"},
                ]
            },
        ),
        make_record(
            "q3",
            {
                "filters": [
                    {"field": "region", "operator": "=", "value": "US"},
                    {"field": "status", "operator": "=", "value": "active"},
                ]
            },
        ),
    ]
    patterns = extract_correction_patterns(records)
    assert len(patterns) == 2
    values = {p["corrected_value"] for p in patterns}
    assert values == {"region=US", "status=active"}


def test_extract_below_threshold_not_returned():
    records = [
        make_record("q1", {"metrics": [{"alias": "revenue"}]}),
        make_record("q2", {"metrics": [{"alias": "revenue"}]}),
    ]
    patterns = extract_correction_patterns(records)
    # frequency 2 < default threshold 3
    assert patterns == []


def test_extract_custom_threshold():
    records = [
        make_record("q1", {"metrics": [{"alias": "revenue"}]}),
        make_record("q2", {"metrics": [{"alias": "revenue"}]}),
    ]
    patterns = extract_correction_patterns(records, min_frequency=2)
    assert len(patterns) == 1
    assert patterns[0]["frequency"] == 2


def test_extract_filter_without_value():
    records = [
        make_record(
            "q1",
            {"filters": [{"field": "region", "operator": "is not null"}]},
        ),
        make_record(
            "q2",
            {"filters": [{"field": "region", "operator": "is not null"}]},
        ),
        make_record(
            "q3",
            {"filters": [{"field": "region", "operator": "is not null"}]},
        ),
    ]
    patterns = extract_correction_patterns(records)
    assert len(patterns) == 1
    assert patterns[0]["corrected_value"] == "region=is not null"


def test_extract_metrics_not_list():
    """Gracefully handle malformed corrected_dsl where metrics is not a list."""
    records = [
        make_record("q1", {"metrics": "not_a_list"}),
        make_record("q2", {"metrics": "not_a_list"}),
        make_record("q3", {"metrics": "not_a_list"}),
    ]
    patterns = extract_correction_patterns(records)
    assert patterns == []


def test_extract_filters_not_list():
    """Gracefully handle malformed corrected_dsl where filters is not a list."""
    records = [
        make_record("q1", {"filters": "not_a_list"}),
        make_record("q2", {"filters": "not_a_list"}),
        make_record("q3", {"filters": "not_a_list"}),
    ]
    patterns = extract_correction_patterns(records)
    assert patterns == []


# ---------------------------------------------------------------------------
# FeedbackProcessor
# ---------------------------------------------------------------------------


class TestFeedbackProcessorInit:
    def test_init_stores_collector_and_registry(self):
        collector = MagicMock(spec=FeedbackCollector)
        registry = {"terms": {}}
        processor = FeedbackProcessor(collector, registry)
        assert processor._collector is collector
        assert processor._registry is registry

    def test_init_tracks_processed_ids(self):
        collector = MagicMock(spec=FeedbackCollector)
        processor = FeedbackProcessor(collector, {})
        assert processor._processed_ids == set()


class TestFeedbackProcessorProcessOnce:
    def test_process_once_no_feedback(self):
        collector = MagicMock(spec=FeedbackCollector)
        collector.list_feedback.return_value = []
        processor = FeedbackProcessor(collector, {})
        result = processor.process_once()
        assert result == []
        assert processor._processed_ids == set()

    def test_process_once_extracts_patterns(self):
        collector = MagicMock(spec=FeedbackCollector)
        collector.list_feedback.return_value = [
            make_record("q1", {"metrics": [{"alias": "revenue"}]}),
            make_record("q2", {"metrics": [{"alias": "revenue"}]}),
            make_record("q3", {"metrics": [{"alias": "revenue"}]}),
        ]
        processor = FeedbackProcessor(collector, {})
        result = processor.process_once()
        assert len(result) == 1
        assert result[0]["correction_type"] == "metric_alias"
        assert result[0]["corrected_value"] == "revenue"
        assert "q1" in processor._processed_ids
        assert "q2" in processor._processed_ids
        assert "q3" in processor._processed_ids

    def test_process_once_skips_already_processed(self):
        collector = MagicMock(spec=FeedbackCollector)
        collector.list_feedback.return_value = [
            make_record("q1", {"metrics": [{"alias": "revenue"}]}),
            make_record("q2", {"metrics": [{"alias": "revenue"}]}),
            make_record("q3", {"metrics": [{"alias": "revenue"}]}),
        ]
        processor = FeedbackProcessor(collector, {})
        processor._processed_ids = {"q1", "q2"}
        result = processor.process_once()
        # Only q3 is new, frequency 1 < threshold
        assert result == []
        assert "q3" in processor._processed_ids

    def test_process_once_with_real_collector(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "feedback.jsonl"
            collector = FeedbackCollector(storage_path=str(path))
            for i in range(3):
                collector.collect(
                    query_id=f"q{i}",
                    user_id="u1",
                    corrected_dsl={"metrics": [{"alias": "gmv"}]},
                )
            processor = FeedbackProcessor(collector, {})
            result = processor.process_once()
            assert len(result) == 1
            assert result[0]["corrected_value"] == "gmv"
            assert result[0]["frequency"] == 3

    def test_process_once_mixed_new_and_old(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "feedback.jsonl"
            collector = FeedbackCollector(storage_path=str(path))
            # First batch
            for i in range(3):
                collector.collect(
                    query_id=f"old{i}",
                    user_id="u1",
                    corrected_dsl={"metrics": [{"alias": "gmv"}]},
                )
            processor = FeedbackProcessor(collector, {})
            processor.process_once()
            # Second batch
            for i in range(3):
                collector.collect(
                    query_id=f"new{i}",
                    user_id="u1",
                    corrected_dsl={"metrics": [{"alias": "gmv"}]},
                )
            result = processor.process_once()
            # Only new batch contributes, frequency 3 >= threshold
            assert len(result) == 1
            assert result[0]["frequency"] == 3
            # processed_ids should include both old and new
            assert len(processor._processed_ids) == 6


class TestFeedbackProcessorUpdateWeights:
    def test_update_logs_patterns(self):
        collector = MagicMock(spec=FeedbackCollector)
        processor = FeedbackProcessor(collector, {})
        patterns = [
            {"correction_type": "metric_alias", "corrected_value": "revenue", "frequency": 5}
        ]
        # MVP: just log, should not raise
        processor._update_term_weights(patterns)

    def test_update_empty_patterns(self):
        collector = MagicMock(spec=FeedbackCollector)
        processor = FeedbackProcessor(collector, {})
        # Should not raise
        processor._update_term_weights([])


class TestFeedbackProcessorRunPeriodically:
    @pytest.mark.asyncio
    async def test_run_periodically_calls_process_once(self):
        collector = MagicMock(spec=FeedbackCollector)
        collector.list_feedback.return_value = []
        processor = FeedbackProcessor(collector, {})

        call_count = 0

        def mock_process_once():
            nonlocal call_count
            call_count += 1
            return []

        processor.process_once = mock_process_once

        # Run for a short time then cancel
        task = asyncio.create_task(processor.run_periodically(interval_seconds=0.05))
        await asyncio.sleep(0.12)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should have been called at least twice in ~120ms with 50ms interval
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_run_periodically_stops_on_cancel(self):
        collector = MagicMock(spec=FeedbackCollector)
        processor = FeedbackProcessor(collector, {})

        task = asyncio.create_task(processor.run_periodically(interval_seconds=0.1))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


def test_end_to_end_with_collector():
    """Full flow: collect feedback → process → extract patterns."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "feedback.jsonl"
        collector = FeedbackCollector(storage_path=str(path))

        # Simulate multiple users correcting the same metric alias
        for i in range(5):
            collector.collect(
                query_id=f"q{i}",
                user_id=f"u{i}",
                corrected_dsl={
                    "metrics": [{"alias": "gmv"}],
                    "filters": [
                        {"field": "region", "operator": "=", "value": "APAC"}
                    ],
                },
            )

        processor = FeedbackProcessor(collector, {})
        patterns = processor.process_once()

        assert len(patterns) == 2
        by_type = {p["correction_type"]: p for p in patterns}
        assert by_type["metric_alias"]["corrected_value"] == "gmv"
        assert by_type["metric_alias"]["frequency"] == 5
        assert by_type["filter"]["corrected_value"] == "region=APAC"
        assert by_type["filter"]["frequency"] == 5
