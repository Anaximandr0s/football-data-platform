"""The Silver job on a bronze lake written to local disk from the tiny match: replay choice, checks, dry run."""
import json
import sys

import pytest

from ingestion.bronze_writer import object_key, to_parquet_bytes
from ingestion.producer_foot import read_records
from spark.silver import bronze_to_silver, config

COMPLETE, OLDER = "t1-20261102T100000Z", "t1-20261101T100000Z"


def write_replay(bronze, prepared, replay_id: str, last_ts: int | None = None) -> None:
    """One replay of the tiny match as bronze_writer stores it; `last_ts` cuts the tracking short."""
    for table in config.BRONZE_TABLES:
        rows = read_records(prepared / "t1" / f"{table}.parquet")
        if table == "tracking" and last_ts is not None:
            rows = [r for r in rows if r["ts"] <= last_ts]
        for offset, row in enumerate(rows):
            row.update(kafka_partition=0, kafka_offset=offset, kafka_ts=0, ingested_at=0, kafka_replay_id=replay_id)
        path = bronze / object_key(table, "t1", replay_id, "2026-11-27", 0, 1)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(to_parquet_bytes(table, rows))


@pytest.fixture
def bronze(tmp_path, prepared, monkeypatch):
    monkeypatch.setattr(config, "QUALITY_DIR", tmp_path / "quality")
    lake = tmp_path / "bronze"
    write_replay(lake, prepared, OLDER)
    write_replay(lake, prepared, COMPLETE)
    write_replay(lake, prepared, "t1-20261103T100000Z", last_ts=3)          # stopped at half-time
    write_replay(lake, prepared, "t1-20261104T100000Z-partial")
    return lake


def test_the_newest_complete_replay_is_cleaned_checked_and_reported(spark, bronze, prepared, tmp_path):
    uri = f"file://{bronze}"
    assert bronze_to_silver.list_matches(spark, uri) == ["t1"]
    assert bronze_to_silver.process_match(spark, "t1", uri, prepared, dry_run=True)
    report = json.loads((tmp_path / "quality" / "silver_t1.json").read_text(encoding="utf-8"))
    assert report["replay_id"] == COMPLETE and report["replays_in_bronze"] == 3
    assert report["checks_passed"] and not report["written"]


def test_a_partial_or_unknown_replay_is_refused(spark, bronze, prepared, capsys):
    uri = f"file://{bronze}"
    assert not bronze_to_silver.process_match(spark, "t1", uri, prepared, True, replay_id="t1-20261104T100000Z-partial")
    assert "partial replay is live only" in capsys.readouterr().err
    assert not bronze_to_silver.process_match(spark, "t1", uri, prepared, True, replay_id="t1-20991231T000000Z")
    assert "not t1-20991231T000000Z" in capsys.readouterr().err


def test_a_replay_with_a_missing_table_is_not_complete(spark, bronze):
    uri = f"file://{bronze}"
    for path in (bronze / "tracking" / "match_id=t1" / f"replay_id={OLDER}").rglob("*.parquet"):
        path.unlink()
    assert not bronze_to_silver.replay_complete(spark, uri, "t1", OLDER)
    assert bronze_to_silver.replay_complete(spark, uri, "t1", COMPLETE)


def test_the_command_line_runs_every_match_and_exits_with_the_result(spark, bronze, prepared, monkeypatch):
    monkeypatch.setattr(bronze_to_silver, "build_spark", lambda **_: spark)
    monkeypatch.setattr(spark, "stop", lambda: None)
    argv = ["bronze_to_silver", "--all", "--dry-run", "--bronze-uri", f"file://{bronze}",
            "--manifest-dir", str(prepared)]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as done:
        bronze_to_silver.main()
    assert done.value.code == 0
    for bad in (["--all", "--match", "t1"], ["--match", "t1", "t2", "--replay", COMPLETE]):
        monkeypatch.setattr(sys, "argv", ["bronze_to_silver", *bad])
        with pytest.raises(SystemExit) as done:
            bronze_to_silver.main()
        assert done.value.code == 2


def test_the_command_line_stops_when_bronze_has_no_match(spark, tmp_path, monkeypatch):
    monkeypatch.setattr(bronze_to_silver, "build_spark", lambda **_: spark)
    monkeypatch.setattr(sys, "argv", ["bronze_to_silver", "--all", "--dry-run", "--bronze-uri", f"file://{tmp_path}"])
    with pytest.raises(SystemExit, match="no match found"):
        bronze_to_silver.main()
