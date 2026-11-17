"""progress.summary: the numbers of one StreamingQueryProgress the pipeline exporter watches."""
import pytest

pytest.importorskip("pyspark")
from spark.streaming import progress  # noqa: E402


def test_the_summary_adds_the_offsets_behind_of_every_kafka_source():
    p = {"batchId": 7, "numInputRows": 300, "inputRowsPerSecond": 60.0, "processedRowsPerSecond": 75.5,
         "durationMs": {"triggerExecution": 1200},
         "sources": [{"metrics": {"maxOffsetsBehindLatest": "10"}, "endOffset": '{"foot-tracking": {"0": 40, "1": 2}}'},
                     {"metrics": {"maxOffsetsBehindLatest": "5"}, "endOffset": {"foot-matches": {"0": 4}}}]}
    assert progress.summary(p) == {"batch_id": 7, "input_rows": 300, "input_rows_per_second": 60.0,
                                   "processed_rows_per_second": 75.5, "batch_duration_ms": 1200,
                                   "offsets_behind_latest": 15.0,
                                   "end_offsets": {"foot-tracking": {"0": 40, "1": 2}, "foot-matches": {"0": 4}}}


def test_a_batch_without_offset_metrics_says_unknown_not_zero():
    p = {"batchId": 0, "inputRowsPerSecond": None, "sources": [{"metrics": {}}]}
    assert progress.summary(p)["offsets_behind_latest"] is None
