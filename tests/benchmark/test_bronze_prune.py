"""bronze_prune.plan: which Bronze files are deleted, never the replay Silver reads."""
import bronze_prune as bp

R = "tracking/match_id=m001/replay_id={}/ingest_date=2026-11-17/part-1-1.parquet"


def test_the_last_complete_replays_and_the_newer_ones_stay_the_rest_goes():
    replays = ["m001-20261117T090000Z", "m001-20261117T100000Z", "m001-20261117T110000Z", "m001-20261117T120000Z",
               "m001-20261117T130000Z"]
    objects = {R.format(r): 10 for r in replays}
    objects["tracking/match_id=m001/ingest_date=2026-11-16/part-1-1.parquet"] = 5          # old layout
    objects[R.format("none")] = 1
    complete = {"m001-20261117T090000Z", "m001-20261117T100000Z", "m001-20261117T110000Z"}  # 12:00, 13:00 stopped
    out = bp.plan(objects, lambda m, r: r in complete, keep=2)
    kept = {bp.parse(k)[2] for k in out["keep"]}
    assert kept == {"m001-20261117T130000Z", "m001-20261117T120000Z", "m001-20261117T110000Z",
                    "m001-20261117T100000Z"}                     # 2 complete (11:00, 10:00) + the newer ones
    assert {bp.parse(k)[2] for k in out["delete"]} == {"m001-20261117T090000Z", None, "none"}


def test_keys_outside_the_layout_are_never_deleted():
    objects = {"tracking/README.txt": 1, R.format("m001-20261117T090000Z"): 10}
    out = bp.plan(objects, lambda m, r: True, keep=1)
    assert out == {"keep": ["tracking/README.txt", R.format("m001-20261117T090000Z")], "delete": []}


def test_a_partial_replay_is_never_kept_as_a_complete_one():
    objects = {R.format(r): 10 for r in ("m001-20261117T090000Z", "m001-20261117T100000Z-partial")}
    seen = []

    def complete(m, r):
        seen.append(r)
        return True
    fn = bp.complete_fn(None, objects)
    assert fn("m001", "m001-20261117T100000Z-partial") is False            # decided by its id, no file read
    out = bp.plan(objects, lambda m, r: fn(m, r) if r.endswith("-partial") else complete(m, r), keep=1)
    assert {bp.parse(k)[2] for k in out["keep"]} == {"m001-20261117T100000Z-partial", "m001-20261117T090000Z"}


class Bucket:
    """The S3 calls of bronze_prune over an in-memory Bronze bucket."""

    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    def get_paginator(self, _name):
        return self

    def paginate(self, Bucket, Prefix):  # noqa: N803 - boto3's names
        return [{"Contents": [{"Key": k, "Size": len(v)} for k, v in self.objects.items() if k.startswith(Prefix)]}]

    def get_object(self, Bucket, Key):  # noqa: N803
        import io
        return {"Body": io.BytesIO(self.objects[Key])}

    def delete_objects(self, Bucket, Delete):  # noqa: N803
        for o in Delete["Objects"]:
            del self.objects[o["Key"]]


def replay(match: str, rid: str, last_ts: int) -> dict[str, bytes]:
    import io

    import pandas as pd

    def parquet(df):
        buf = io.BytesIO()
        df.to_parquet(buf)
        return buf.getvalue()
    folder = f"match_id={match}/replay_id={rid}/ingest_date=2026-11-27/part-1.parquet"
    return {f"matches/{folder}": parquet(pd.DataFrame({"p2_end_ts": [90]})),
            f"tracking/{folder}": parquet(pd.DataFrame({"ts": range(last_ts + 1)}))}


def prune(monkeypatch, bucket, *args):
    import sys

    monkeypatch.setenv("MINIO_ROOT_USER", "u")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "p")
    monkeypatch.setattr(bp.boto3, "client", lambda *a, **k: bucket)
    monkeypatch.setattr(sys, "argv", ["bronze_prune.py", *args])
    bp.main()


def test_the_command_shows_first_then_deletes_the_older_replays(monkeypatch, capsys):
    bucket = Bucket({**replay("m1", "m1-20261101T100000Z", 90), **replay("m1", "m1-20261102T100000Z", 40),
                     **replay("m1", "m1-20261103T100000Z", 90), **replay("m1", "m1-20261104T100000Z-partial", 90),
                     "tracking/match_id=m1/ingest_date=2026-11-01/old.parquet": b"x"})
    prune(monkeypatch, bucket, "--keep", "1")
    out = capsys.readouterr().out
    assert "would delete  m1  m1-20261101T100000Z" in out and "old layout" in out and "nothing deleted" in out
    assert len(bucket.objects) == 9
    prune(monkeypatch, bucket, "--keep", "1", "--delete")
    assert sorted({k.split("/")[2] for k in bucket.objects}) == ["replay_id=m1-20261103T100000Z",
                                                                  "replay_id=m1-20261104T100000Z-partial"]


def test_the_command_never_deletes_the_replay_silver_reads(monkeypatch):
    import pytest
    with pytest.raises(SystemExit):
        prune(monkeypatch, Bucket({}), "--keep", "0")
