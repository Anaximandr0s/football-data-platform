"""Tests of the pure helpers of producer_foot.py (no Kafka needed)."""

import pandas as pd

from ingestion import replay_ids
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


def test_a_replay_id_names_the_match_and_its_utc_start():
    import datetime as dt

    started = dt.datetime(2026, 11, 16, 11, 15, 3, tzinfo=dt.timezone(dt.timedelta(hours=1)))  # 10:15:03 UTC
    assert replay_ids.make("m001", started) == "m001-20261116T101503Z"
    partial = replay_ids.make("m001", started, partial=True)
    assert partial == "m001-20261116T101503Z-partial" and replay_ids.is_partial(partial)
    assert replay_ids.match_of(partial) == replay_ids.match_of("m001-20261116T101503Z") == "m001"
    assert not replay_ids.is_partial("m001-20261116T101503Z")
