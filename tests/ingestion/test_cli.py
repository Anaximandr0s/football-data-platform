"""The ingestion command lines end to end on the tiny hand-made match: no network, no Kafka, no MinIO."""

import io
import json
import urllib.error

import confluent_kafka
import pandas as pd
import pytest

from ingestion import check_bronze, download_foot, ingest_foot, producer_foot
from tests.conftest import SC_ID, run


def test_ingest_writes_five_tables_and_a_manifest_that_matches_them(prepared):
    manifest = json.loads((prepared / "t1" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["tracking_rows"] == len(pd.read_parquet(prepared / "t1" / "tracking.parquet")) == 21
    assert manifest["players"] == 4 and manifest["seconds_with_data"] == 7
    assert manifest["goals_derived_home_away"] == manifest["score_real_home_away"] == [1, 0]
    assert manifest["dropped_rows"]["player_not_in_lineup"] == 7


def test_ingest_warns_when_the_derived_goals_differ_from_the_score(raw_dir, tmp_path, monkeypatch, capsys):
    path = raw_dir / str(SC_ID) / f"{SC_ID}_match.json"
    info = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**info, "home_team_score": 3}), encoding="utf-8")
    run(
        ingest_foot,
        monkeypatch,
        "--match",
        "t1",
        "--sc-id",
        str(SC_ID),
        "--raw-dir",
        str(raw_dir),
        "--out",
        str(tmp_path / "out"),
    )
    assert "derived goals differ" in capsys.readouterr().err


def test_ingest_refuses_missing_files_and_other_pitch_sizes(raw_dir, tmp_path, monkeypatch):
    args = ["--match", "t1", "--sc-id", str(SC_ID), "--raw-dir", str(raw_dir), "--out", str(tmp_path)]
    path = raw_dir / str(SC_ID) / f"{SC_ID}_match.json"
    info = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**info, "pitch_length": 100}), encoding="utf-8")
    with pytest.raises(SystemExit, match="pitch is 100x68"):
        run(ingest_foot, monkeypatch, *args)
    path.unlink()
    with pytest.raises(SystemExit, match="missing in .*_match.json"):
        run(ingest_foot, monkeypatch, *args)


def test_a_dry_run_replays_every_row_without_kafka(prepared, monkeypatch, capsys):
    run(producer_foot, monkeypatch, "--match", "t1", "--speed", "60", "--data-dir", str(prepared), "--dry-run")
    out = capsys.readouterr().out
    assert "replay_id=t1-" in out and "-partial" not in out
    assert "tracking=21" in out and "players=4" in out and "matches=1" in out


def test_a_replay_started_late_is_partial_and_skips_the_earlier_seconds(prepared, monkeypatch, capsys):
    run(
        producer_foot,
        monkeypatch,
        "--match",
        "t1",
        "--speed",
        "60",
        "--start",
        "5",
        "--data-dir",
        str(prepared),
        "--dry-run",
    )
    out = capsys.readouterr().out
    assert "-partial" in out and "tracking=12" in out


def test_the_producer_rejects_a_bad_speed_and_an_unknown_match(prepared, monkeypatch):
    with pytest.raises(SystemExit):
        run(producer_foot, monkeypatch, "--match", "t1", "--speed", "61", "--dry-run")
    with pytest.raises(SystemExit, match="not found"):
        run(producer_foot, monkeypatch, "--match", "nope", "--data-dir", str(prepared), "--dry-run")


class FakeProducer:
    """confluent_kafka.Producer: the first produce() finds a full queue, deliveries can fail."""

    def __init__(self, fail: bool):
        self.sent, self.fail, self.full_once = [], fail, True

    def produce(self, topic, key, value, headers, on_delivery):
        if self.full_once:
            self.full_once = False
            raise BufferError
        self.sent.append((topic, key, json.loads(value), dict(headers)))
        on_delivery("broker down" if self.fail else None, None)

    def poll(self, _timeout):
        return 0

    def flush(self, _timeout):
        return 0


@pytest.mark.parametrize("fail", [False, True])
def test_the_producer_keys_each_topic_and_tags_every_message_with_its_replay(prepared, monkeypatch, fail):
    fake = FakeProducer(fail)
    monkeypatch.setattr(confluent_kafka, "Producer", lambda _conf: fake)
    args = ["--match", "t1", "--speed", "60", "--data-dir", str(prepared)]
    if fail:
        with pytest.raises(SystemExit, match="FAILED: 39 delivery errors"):
            run(producer_foot, monkeypatch, *args)
        return
    run(producer_foot, monkeypatch, *args)
    topics = {t for t, *_ in fake.sent}
    assert topics == {"foot-matches", "foot-players", "foot-tracking", "foot-events", "foot-ball"}
    assert len(fake.sent) == 39 and fake.sent[0][0] == "foot-matches"  # reference tables first
    assert all(h["replay_id"].startswith(b"t1-") for *_, h in fake.sent)
    tracking = [(k, v) for t, k, v, _ in fake.sent if t == "foot-tracking"]
    assert all(k == v["player_id"] for k, v in tracking)


class FakeS3:
    """The two calls of boto3's S3 client that check_bronze uses, over an in-memory bucket."""

    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    def get_paginator(self, _name):
        return self

    def paginate(self, Bucket, Prefix, Delimiter=None):  # noqa: N803 - boto3's names
        keys = [k for k in self.objects if k.startswith(Prefix)]
        if Delimiter:
            prefixes = sorted({Prefix + k[len(Prefix) :].split(Delimiter)[0] + Delimiter for k in keys})
            return [{"CommonPrefixes": [{"Prefix": p} for p in prefixes]}]
        return [{"Contents": [{"Key": k} for k in keys]}]

    def get_object(self, Bucket, Key):  # noqa: N803
        return {"Body": io.BytesIO(self.objects[Key])}


def parquet_bytes(rows: int) -> bytes:
    buf = io.BytesIO()
    pd.DataFrame({"ts": range(rows)}).to_parquet(buf)
    return buf.getvalue()


@pytest.fixture
def bronze(prepared, monkeypatch):
    monkeypatch.setattr(check_bronze, "PREPARED_DIR", prepared)
    monkeypatch.setenv("MINIO_ROOT_USER", "u")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "p")

    def install(objects):
        monkeypatch.setattr(check_bronze.boto3, "client", lambda *a, **k: FakeS3(objects))

    return install


def replay_objects(replay: str, tracking_rows: int) -> dict[str, bytes]:
    rows = {"tracking": tracking_rows, "events": 7, "ball": 7, "players": 4, "matches": 1}
    return {f"{t}/match_id=t1/replay_id={replay}/part-0.parquet": parquet_bytes(n) for t, n in rows.items()}


def test_check_bronze_counts_the_newest_complete_replay(bronze, monkeypatch, capsys):
    old, new = "t1-20261101T100000Z", "t1-20261102T100000Z"
    bronze({**replay_objects(old, 1), **replay_objects(new, 22), **replay_objects("t1-20261103T100000Z-partial", 1)})
    with pytest.raises(SystemExit) as done:
        run(check_bronze, monkeypatch, "--match", "t1")
    out = capsys.readouterr().out
    assert done.value.code == 0 and f"replay {new}" in out
    assert "tracking  bronze=     22 expected=     21  MORE" in out and "players   bronze=      4" in out


def test_check_bronze_fails_when_rows_are_missing(bronze, monkeypatch, capsys):
    bronze(replay_objects("t1-20261101T100000Z", 3))
    with pytest.raises(SystemExit) as done:
        run(check_bronze, monkeypatch, "--match", "t1")
    assert done.value.code == 1 and "MISSING" in capsys.readouterr().out


def test_check_bronze_refuses_a_partial_replay_and_a_match_never_replayed(bronze, monkeypatch):
    bronze({})
    with pytest.raises(SystemExit, match="started after kick-off"):
        run(check_bronze, monkeypatch, "--match", "t1", "--replay", "t1-20261101T100000Z-partial")
    with pytest.raises(SystemExit, match="no replay folder"):
        run(check_bronze, monkeypatch, "--match", "t1")


@pytest.fixture
def github(tmp_path, monkeypatch):
    """SkillCorner's repository: matches.json lists ids 1 to 5, every file downloads as `data`."""
    monkeypatch.setattr(download_foot, "RAW_DIR", tmp_path)
    monkeypatch.setattr(
        download_foot.urllib.request,
        "urlopen",
        lambda url, timeout: io.BytesIO(json.dumps([{"id": i} for i in (3, 1, 5, 2, 4)]).encode()),
    )
    fetched = []

    def urlretrieve(url, part):
        fetched.append(url)
        part.write_bytes(b"data")

    monkeypatch.setattr(download_foot.urllib.request, "urlretrieve", urlretrieve)
    return fetched


def test_download_fetches_three_files_per_match_and_skips_those_already_there(github, tmp_path, monkeypatch):
    (tmp_path / "7").mkdir()
    (tmp_path / "7" / "7_match.json").write_text("{}")
    run(download_foot, monkeypatch, "7")
    assert [u.rsplit("/", 1)[1] for u in github] == ["7_dynamic_events.csv", "7_tracking_extrapolated.jsonl"]
    assert github[1].startswith("https://media.githubusercontent.com/")  # tracking is Git LFS
    assert (tmp_path / "7" / "7_tracking_extrapolated.jsonl").read_bytes() == b"data"
    assert not list(tmp_path.glob("7/*.part"))


def test_download_lists_and_picks_reproducible_random_ids(github, monkeypatch, capsys):
    run(download_foot, monkeypatch, "--list")
    assert capsys.readouterr().out.split() == ["1", "2", "3", "4", "5"]
    run(download_foot, monkeypatch, "--random", "2", "--seed", "7")
    first = capsys.readouterr().out.splitlines()[-1]
    run(download_foot, monkeypatch, "--random", "2", "--seed", "7")
    assert capsys.readouterr().out.splitlines()[-1] == first
    with pytest.raises(SystemExit):
        run(download_foot, monkeypatch)


def test_download_stops_on_an_lfs_pointer_or_an_http_error(tmp_path, monkeypatch):
    target = tmp_path / "f.jsonl"
    monkeypatch.setattr(
        download_foot.urllib.request,
        "urlretrieve",
        lambda url, part: part.write_bytes(b"version https://git-lfs.github.com/spec/v1"),
    )
    with pytest.raises(SystemExit, match="Git LFS pointer"):
        download_foot.fetch("u", target)
    assert not list(tmp_path.iterdir())

    def not_found(url, part):
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)

    monkeypatch.setattr(download_foot.urllib.request, "urlretrieve", not_found)
    with pytest.raises(SystemExit, match="HTTP 404"):
        download_foot.fetch("u", target)
