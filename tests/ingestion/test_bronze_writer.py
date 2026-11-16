"""Tests of the pure helpers of bronze_writer.py (no Kafka, no MinIO needed)."""
import io

import pyarrow.parquet as pq

from ingestion.bronze_writer import replay_id_of, to_parquet_bytes
from ingestion.schemas import bronze_schema


def test_bronze_bytes_follow_the_contract_columns_and_keep_nulls():
    row = {"match_id": "m001", "ts": 1, "period": 1, "x": 1.0, "y": 2.0, "z": None,
           "kafka_partition": 0, "kafka_offset": 5, "kafka_ts": 1, "ingested_at": 2}
    table = pq.read_table(io.BytesIO(to_parquet_bytes("ball", [row])))
    assert table.schema.names == bronze_schema("ball").names
    assert table.num_rows == 1 and table.column("z").null_count == 1

def test_a_message_without_the_newer_columns_is_written_with_nulls():
    """A message replayed before possession existed must still fit the bronze schema."""
    row = {"match_id": "m001", "ts": 1, "period": 1, "x": 1.0, "y": 2.0, "z": 0.0,
           "kafka_partition": 0, "kafka_offset": 5, "kafka_ts": 1, "ingested_at": 2}
    table = pq.read_table(io.BytesIO(to_parquet_bytes("ball", [row])))
    assert table.column("possession").null_count == 1


def test_event_booleans_and_xthreat_keep_their_types_in_bronze():
    row = {"match_id": "m001", "event_id": "m001-r00001", "ts": 3, "period": 1, "player_id": "H01",
           "receiver_id": None, "team_id": "HOME", "type": "run", "x_start": 1.0, "y_start": 2.0,
           "x_end": 3.0, "y_end": 4.0, "outcome": "n/a", "phase": "create", "phase_against": "low_block",
           "xthreat": 0.12, "dangerous": True, "speed_band": "hsr", "subtype": "behind", "lead_to_shot": False,
           "targeted": True, "received": None,
           "kafka_partition": 0, "kafka_offset": 5, "kafka_ts": 1, "ingested_at": 2}
    table = pq.read_table(io.BytesIO(to_parquet_bytes("events", [row])))
    got = table.to_pylist()[0]
    assert (got["xthreat"], got["dangerous"], got["targeted"], got["received"]) == (0.12, True, True, None)
    assert str(table.schema.field("dangerous").type) == "bool"


def test_the_replay_id_header_becomes_a_column_and_is_null_without_it():
    assert replay_id_of([("other", b"x"), ("replay_id", b"m001-20261116T101503Z")]) == "m001-20261116T101503Z"
    assert replay_id_of(None) is None and replay_id_of([]) is None
    row = {"match_id": "m001", "ts": 1, "period": 1, "x": 1.0, "y": 2.0, "z": 0.0, "kafka_partition": 0,
           "kafka_offset": 5, "kafka_ts": 1, "ingested_at": 2, "kafka_replay_id": "m001-20261116T101503Z"}
    old = {k: v for k, v in row.items() if k != "kafka_replay_id"}           # a message without the header
    table = pq.read_table(io.BytesIO(to_parquet_bytes("ball", [row, old])))
    assert table.column("kafka_replay_id").to_pylist() == ["m001-20261116T101503Z", None]
