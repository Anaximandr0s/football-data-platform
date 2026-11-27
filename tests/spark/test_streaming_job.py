"""The aggregations of the streaming job on the tiny match, with batch tables in place of the Kafka topics."""

import datetime as dt
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

CLOCK = Path(__file__).resolve().parents[2] / "app" / "streamlit" / "clock.py"
sys.path.insert(0, str(CLOCK.parent))  # clock.py, as the job ships it
from ingestion.producer_foot import read_records  # noqa: E402
from spark.streaming import live_stats, progress  # noqa: E402

REPLAY = "t1-20261127T100000Z"
SENT_AT = dt.datetime(2026, 11, 27, 10)


@pytest.fixture
def topics(spark, prepared, tmp_path, monkeypatch):
    """Every replay topic as the job parses it, read as a file stream; each tracking message arrives twice."""
    spark.sparkContext.addPyFile(str(CLOCK))

    def frame(name: str):
        cols = [c.split()[0] for c in live_stats.SCHEMA[name].split(", ")]
        records = read_records(prepared / "t1" / f"{name}.parquet") * (2 if name == "tracking" else 1)
        rows = [(REPLAY, SENT_AT, *(r[c] for c in cols)) for r in records]
        return spark.createDataFrame(rows, f"replay_id string, kafka_time timestamp, {live_stats.SCHEMA[name]}")

    def stream(_spark, name: str):
        folder = tmp_path / "topics" / name
        if not folder.exists():
            frame(name).write.parquet(str(folder))
        return spark.readStream.schema(frame(name).schema).parquet(str(folder))

    monkeypatch.setattr(live_stats, "stream", stream)
    monkeypatch.setattr(live_stats, "static", lambda _spark, name: frame(name).drop("kafka_time"))
    return live_stats.static(spark, "matches")


def collect(spark, query, name: str) -> list:
    """Run a streaming aggregation over everything available, as one update batch."""
    (
        query.writeStream.format("memory")
        .queryName(name)
        .outputMode("update")
        .trigger(availableNow=True)
        .start()
        .awaitTermination()
    )
    return spark.table(name).collect()


def test_player_windows_count_each_second_once_and_null_impossible_speeds(spark, topics):
    rows = {
        r.player_id: r
        for r in collect(spark, live_stats.player_counts(spark, topics), "players")
        if r.window_index == 0
    }
    assert sorted(rows) == ["A01", "H01", "H02"]  # H03 comes on at half-time
    keeper = rows["H01"]
    assert (keeper.team_id, keeper.tracked_seconds, keeper.last_ts) == ("HOME", 3, 3)  # duplicates counted once
    assert keeper.distance_m == pytest.approx(1.0) and keeper.max_speed_kmh == pytest.approx(3.6)
    assert keeper.sprint_seconds == 0


def test_team_windows_split_possession_passes_and_defensive_actions_by_third(spark, topics):
    first_half = next(
        r for r in collect(spark, live_stats.team_counts(spark, topics, 300), "teams") if r.window_index == 0
    )
    assert (first_half.home_possession, first_half.away_possession) == (1, 1)
    assert (first_half.home_passes, first_half.away_da) == (1, 2)  # a pressure and a tackle
    assert first_half.away_da_own + first_half.away_da_middle + first_half.away_da_final == 2
    second_half = next(
        r for r in collect(spark, live_stats.team_counts(spark, topics, 900), "pressing") if r.window_index > 3
    )
    assert second_half.away_da == 1  # the foul of period 2


def test_the_progress_file_follows_each_query_from_start_to_end(tmp_path):
    path = tmp_path / "progress.json"
    listener = progress.ProgressFile(path)
    listener.onQueryStarted(SimpleNamespace(name="players-5min", id="q1"))
    batch = {
        "name": "players-5min",
        "id": "q1",
        "batchId": 4,
        "numInputRows": 22,
        "durationMs": {"triggerExecution": 900},
        "sources": [{"endOffset": {"foot-tracking": {"0": 120}}, "metrics": {"maxOffsetsBehindLatest": "3"}}],
    }
    listener.onQueryProgress(SimpleNamespace(progress=SimpleNamespace(json=json.dumps(batch))))
    saved = json.loads(path.read_text(encoding="utf-8"))["players-5min"]
    assert (saved["batch_id"], saved["offsets_behind_latest"], saved["running"]) == (4, 3.0, True)
    listener.onQueryIdle(SimpleNamespace(id="q1"))
    assert json.loads(path.read_text(encoding="utf-8"))["players-5min"]["input_rows_per_second"] == 0.0
    listener.onQueryTerminated(SimpleNamespace(id="q1"))
    assert json.loads(path.read_text(encoding="utf-8"))["players-5min"]["running"] is False
    assert not list(tmp_path.glob("*.tmp"))
