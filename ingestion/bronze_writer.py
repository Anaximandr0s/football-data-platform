"""bronze_writer.py (step 4): Kafka -> MinIO bronze, as Parquet micro-batches partitioned by match.

    python -m ingestion.bronze_writer                       # run until Ctrl+C
    python -m ingestion.bronze_writer --exit-when-idle 30   # stop 30 s after the last message

Layout: s3://bronze/<table>/match_id=<id>/ingest_date=<YYYY-MM-DD>/part-<epoch_ms>-<n>.parquet
Tables: tracking, events, ball, players, matches (one per Kafka topic).
Rows are stored as received + kafka_partition, kafka_offset, kafka_ts, ingested_at, kafka_replay_id (the replay_id
header, null for messages sent before it existed), with the
fixed column types of schemas.py. A file is written every 10 s or 5,000 rows, per (table, match).
Offsets are committed after the upload, so delivery is at-least-once: Silver must deduplicate.
"""
import argparse
import io
import json
import os
import sys
import time
from collections import defaultdict

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
from confluent_kafka import Consumer

from ingestion.config import BRONZE_BUCKET, KAFKA_BOOTSTRAP, REPLAY_HEADER, S3_ENDPOINT, TOPICS
from ingestion.schemas import bronze_schema

TABLE_OF = {topic: table for table, topic in TOPICS.items()}
BATCH_MSGS, BATCH_SECONDS = 5000, 10


def to_parquet_bytes(table: str, rows: list[dict]) -> bytes:
    """Rows -> Parquet bytes with the fixed bronze schema of the table."""
    buf = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(rows, schema=bronze_schema(table)), buf)
    return buf.getvalue()


def replay_id_of(headers: list[tuple[str, bytes]] | None) -> str | None:
    """The replay_id header of a message, None when it has none (sent before the header existed)."""
    for name, value in headers or []:
        if name == REPLAY_HEADER and value is not None:
            return value.decode()
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--exit-when-idle", type=float, default=0, metavar="SECONDS",
                    help="stop after this many seconds without message (0 = never)")
    a = ap.parse_args()

    s3 = boto3.client("s3", endpoint_url=S3_ENDPOINT, region_name="us-east-1",
                      aws_access_key_id=os.environ["MINIO_ROOT_USER"],
                      aws_secret_access_key=os.environ["MINIO_ROOT_PASSWORD"])
    c = Consumer({"bootstrap.servers": KAFKA_BOOTSTRAP,
                  "group.id": os.getenv("BRONZE_GROUP", "bronze-writer"),
                  "auto.offset.reset": "earliest", "enable.auto.commit": False})
    c.subscribe(list(TOPICS.values()))

    buf: dict[tuple[str, str], list[dict]] = defaultdict(list)
    n_buf, part, got_any = 0, 0, False
    last_flush = last_msg = time.time()

    def flush() -> None:
        nonlocal buf, n_buf, last_flush, part
        for (table, match_id), rows in buf.items():
            part += 1
            day = time.strftime("%Y-%m-%d", time.gmtime())
            key = f"{table}/match_id={match_id}/ingest_date={day}/part-{int(time.time() * 1000)}-{part}.parquet"
            s3.put_object(Bucket=BRONZE_BUCKET, Key=key, Body=to_parquet_bytes(table, rows))
            print(f"wrote {len(rows):>5} rows -> s3://{BRONZE_BUCKET}/{key}", flush=True)
        if n_buf:
            c.commit(asynchronous=False)
        buf, n_buf, last_flush = defaultdict(list), 0, time.time()

    try:
        while True:
            msg = c.poll(1.0)
            if msg is not None:
                if msg.error():
                    print(f"kafka error: {msg.error()}", file=sys.stderr)
                else:
                    row = json.loads(msg.value())
                    row.update(kafka_partition=msg.partition(), kafka_offset=msg.offset(),
                               kafka_ts=msg.timestamp()[1], ingested_at=int(time.time() * 1000),
                               kafka_replay_id=replay_id_of(msg.headers()))
                    buf[(TABLE_OF[msg.topic()], row["match_id"])].append(row)
                    n_buf += 1
                    got_any, last_msg = True, time.time()
            if n_buf and (n_buf >= BATCH_MSGS or time.time() - last_flush >= BATCH_SECONDS):
                flush()
            if a.exit_when_idle and got_any and time.time() - last_msg > a.exit_when_idle:
                flush()
                break
    except KeyboardInterrupt:
        flush()
    finally:
        c.close()


if __name__ == "__main__":
    main()