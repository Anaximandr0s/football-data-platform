"""Tests of the pure helpers of producer_foot.py (no Kafka needed)."""
import pandas as pd

from ingestion.producer_foot import by_ts, read_records


def test_by_ts_groups_records_per_second():
    grouped = by_ts([{"ts": 1, "a": 1}, {"ts": 1, "a": 2}, {"ts": 3, "a": 3}])
    assert sorted(grouped) == [1, 3] and len(grouped[1]) == 2


def test_read_records_turns_nan_into_null(tmp_path):
    path = tmp_path / "t.parquet"
    pd.DataFrame({"ts": [1], "speed_kmh": [float("nan")]}).to_parquet(path)
    assert read_records(path) == [{"ts": 1, "speed_kmh": None}]

def test_read_records_sends_missing_booleans_as_null(tmp_path):
    path = tmp_path / "t.parquet"
    pd.DataFrame({"ts": [1, 2], "targeted": pd.array([True, None], dtype="boolean")}).to_parquet(path)
    assert read_records(path) == [{"ts": 1, "targeted": True}, {"ts": 2, "targeted": None}]
