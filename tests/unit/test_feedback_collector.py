import json
import tempfile
import os
from nl2dsl.feedback.collector import FeedbackCollector


def test_collect_feedback():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "feedback.jsonl")
        collector = FeedbackCollector(storage_path=path)

        collector.collect(
            query_id="q001",
            user_id="u123",
            corrected_dsl={"data_source": "orders"},
            comment="应该是GMV",
        )

        records = collector.list_feedback()
        assert len(records) == 1
        assert records[0]["query_id"] == "q001"
        assert records[0]["comment"] == "应该是GMV"


def test_list_feedback_limit():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "feedback.jsonl")
        collector = FeedbackCollector(storage_path=path)

        for i in range(5):
            collector.collect(query_id=f"q{i}", user_id="u123")

        records = collector.list_feedback(limit=3)
        assert len(records) == 3
        assert records[-1]["query_id"] == "q4"
