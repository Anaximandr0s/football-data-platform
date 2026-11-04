"""Tests of the pure helpers of bronze_writer.py (no Kafka, no MinIO needed)."""
import io

import pyarrow.parquet as pq

from ingestion.bronze_writer import to_parquet_bytes
from ingestion.schemas import bronze_schema


def test_bronze_bytes_follow_the_contract_columns_and_keep_nulls():
    row = {"match_id": "m001", "ts": 1, "period": 1, "x": 1.0, "y": 2.0, "z": None,
           "kafka_partition": 0, "kafka_offset": 5, "kafka_ts": 1, "ingested_at": 2}
    table = pq.read_table(io.BytesIO(to_parquet_bytes("ball", [row])))
    assert table.schema.names == bronze_schema("ball").names
    assert table.num_rows == 1 and table.column("z").null_count == 1