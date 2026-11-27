"""Tests of the pure helpers of bronze_writer.py (no Kafka, no MinIO needed)."""

import io

import pyarrow.parquet as pq

from ingestion.bronze_writer import replay_id_of, to_parquet_bytes
from ingestion.schemas import bronze_schema


def test_bronze_bytes_follow_the_contract_columns_and_keep_nulls():
    row = {
        "match_id": "m001",
        "ts": 1,
        "period": 1,
        "x": 1.0,
        "y": 2.0,
        "z": None,
        "kafka_partition": 0,
        "kafka_offset": 5,
        "kafka_ts": 1,
        "ingested_at": 2,
    }
    table = pq.read_table(io.BytesIO(to_parquet_bytes("ball", [row])))
    assert table.schema.names == bronze_schema("ball").names
    assert table.num_rows == 1 and table.column("z").null_count == 1


def test_a_message_without_the_newer_columns_is_written_with_nulls():
    """A message replayed before possession existed must still fit the bronze schema."""
    row = {
        "match_id": "m001",
        "ts": 1,
        "period": 1,
        "x": 1.0,
        "y": 2.0,
        "z": 0.0,
        "kafka_partition": 0,
        "kafka_offset": 5,
        "kafka_ts": 1,
        "ingested_at": 2,
    }
    table = pq.read_table(io.BytesIO(to_parquet_bytes("ball", [row])))
    assert table.column("possession").null_count == 1


def test_event_booleans_and_xthreat_keep_their_types_in_bronze():
    row = {
        "match_id": "m001",
        "event_id": "m001-r00001",
        "ts": 3,
        "period": 1,
        "player_id": "H01",
        "receiver_id": None,
        "team_id": "HOME",
        "type": "run",
        "x_start": 1.0,
        "y_start": 2.0,
        "x_end": 3.0,
        "y_end": 4.0,
        "outcome": "n/a",
        "phase": "create",
        "phase_against": "low_block",
        "xthreat": 0.12,
        "dangerous": True,
        "speed_band": "hsr",
        "subtype": "behind",
        "lead_to_shot": False,
        "targeted": True,
        "received": None,
        "kafka_partition": 0,
        "kafka_offset": 5,
        "kafka_ts": 1,
        "ingested_at": 2,
    }
    table = pq.read_table(io.BytesIO(to_parquet_bytes("events", [row])))
    got = table.to_pylist()[0]
    assert (got["xthreat"], got["dangerous"], got["targeted"], got["received"]) == (0.12, True, True, None)
    assert str(table.schema.field("dangerous").type) == "bool"


def test_the_replay_id_header_becomes_a_column_and_is_null_without_it():
    assert replay_id_of([("other", b"x"), ("replay_id", b"m001-20261116T101503Z")]) == "m001-20261116T101503Z"
    assert replay_id_of(None) is None and replay_id_of([]) is None
    row = {
        "match_id": "m001",
        "ts": 1,
        "period": 1,
        "x": 1.0,
        "y": 2.0,
        "z": 0.0,
        "kafka_partition": 0,
        "kafka_offset": 5,
        "kafka_ts": 1,
        "ingested_at": 2,
        "kafka_replay_id": "m001-20261116T101503Z",
    }
    old = {k: v for k, v in row.items() if k != "kafka_replay_id"}  # a message without the header
    table = pq.read_table(io.BytesIO(to_parquet_bytes("ball", [row, old])))
    assert table.column("kafka_replay_id").to_pylist() == ["m001-20261116T101503Z", None]


# ---------------------------------------------------------------- the loop: layout per replay, clean stop

import json  # noqa: E402
import os  # noqa: E402
import signal  # noqa: E402

from ingestion import bronze_writer as bw  # noqa: E402


class Msg:
    def __init__(self, topic: str, offset: int, replay: str | None, ts: int = 1):
        self._topic, self._offset, self._replay, self._ts = topic, offset, replay, ts

    def error(self):
        return None

    def topic(self):
        return self._topic

    def partition(self):
        return 0

    def offset(self):
        return self._offset

    def timestamp(self):
        return (1, 1_700_000_000_000)

    def headers(self):
        return [("replay_id", self._replay.encode())] if self._replay else None

    def value(self):
        return json.dumps(
            {
                "match_id": "m001",
                "ts": self._ts,
                "period": 1,
                "player_id": "H01",
                "team_id": "HOME",
                "x": 1.0,
                "y": 2.0,
                "detected": True,
            }
        ).encode()


class FakeConsumer:
    """Gives its messages one per poll; `on_poll(n)` runs before the n-th poll."""

    def __init__(self, messages, on_poll=None):
        self.messages, self.on_poll, self.polls, self.commits, self.closed = list(messages), on_poll, 0, 0, False

    def poll(self, _timeout):
        self.polls += 1
        if self.on_poll:
            self.on_poll(self.polls)
        return self.messages.pop(0) if self.messages else None

    def commit(self, asynchronous=True):
        self.commits += 1

    def close(self):
        self.closed = True


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body):  # noqa: N803 - boto3's names
        self.objects[Key] = Body


def test_each_replay_gets_its_own_folder():
    assert (
        bw.object_key("tracking", "m001", "m001-20261117T120000Z", "2026-11-17", 5, 2)
        == "tracking/match_id=m001/replay_id=m001-20261117T120000Z/ingest_date=2026-11-17/part-5-2.parquet"
    )
    assert "/replay_id=none/" in bw.object_key("ball", "m001", None, "2026-11-17", 5, 2)


def test_sigterm_writes_the_buffer_commits_and_closes(monkeypatch):
    stop = bw.Stop()
    signal.signal(signal.SIGTERM, stop)
    messages = [Msg("foot-tracking", i, "m001-A" if i < 3 else "m001-B") for i in range(5)]
    c = FakeConsumer(messages, on_poll=lambda n: os.kill(os.getpid(), signal.SIGTERM) if n == 6 else None)
    s3 = FakeS3()
    bw.run(c, s3, stop=stop)  # returns: no 10 s wait, nothing killed
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    rows = {k.split("/")[2]: pq.read_table(io.BytesIO(v)).num_rows for k, v in s3.objects.items()}
    assert rows == {"replay_id=m001-A": 3, "replay_id=m001-B": 2}  # the 5 buffered rows, one file per replay
    assert (c.commits, c.closed) == (1, True)


def test_idle_exit_writes_and_commits_too():
    c, s3 = FakeConsumer([Msg("foot-tracking", 0, "m001-A")]), FakeS3()
    bw.run(c, s3, exit_when_idle=0.01)
    assert len(s3.objects) == 1 and c.commits == 1 and c.closed
