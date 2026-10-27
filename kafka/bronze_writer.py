"""bronze_writer: Kafka -> MinIO Bronze (Parquet micro-batches, partitioned by match_id).

  python kafka/bronze_writer.py        (needs: confluent-kafka pyarrow pandas boto3)

Keys written:  s3://bronze/tracking/match_id=m001/part-<epoch_ms>-<n>.parquet
               s3://bronze/events/match_id=m001/part-<epoch_ms>-<n>.parquet
Delivery is at-least-once (offsets are committed after the upload), so Silver must
deduplicate on (match_id, player_id, ts). Messages are kept as received + Kafka metadata.
"""
import io
import json
import os
import time
from collections import defaultdict

import boto3
import pandas as pd
from confluent_kafka import Consumer

BOOTSTRAP = os.getenv("KAFKA_EXTERNAL_BOOTSTRAP", "localhost:29092")
TOPICS = {os.getenv("KAFKA_TOPIC_TRACKING", "foot-tracking"): "tracking",
          os.getenv("KAFKA_TOPIC_EVENTS", "foot-events"): "events"}
BUCKET = os.getenv("MINIO_BUCKET_BRONZE", "bronze")
ENDPOINT = os.getenv("MINIO_ENDPOINT", f"http://localhost:{os.getenv('MINIO_API_PORT', '9000')}")
BATCH_MSGS, BATCH_SECONDS = 5000, 10


def to_parquet_bytes(rows: list[dict]) -> bytes:
    buf = io.BytesIO()
    pd.DataFrame(rows).to_parquet(buf, index=False)
    return buf.getvalue()


def main() -> None:
    s3 = boto3.client("s3", endpoint_url=ENDPOINT,
                      aws_access_key_id=os.getenv("MINIO_ROOT_USER", "minioadmin"),
                      aws_secret_access_key=os.environ["MINIO_ROOT_PASSWORD"])
    c = Consumer({"bootstrap.servers": BOOTSTRAP, "group.id": "bronze-writer",
                  "auto.offset.reset": "earliest", "enable.auto.commit": False})
    c.subscribe(list(TOPICS))
    buf: dict[tuple[str, str], list[dict]] = defaultdict(list)
    n_buf, last, part = 0, time.time(), 0

    def flush():
        nonlocal buf, n_buf, last, part
        for (table, match_id), rows in buf.items():
            part += 1
            key = f"{table}/match_id={match_id}/part-{int(time.time() * 1000)}-{part}.parquet"
            s3.put_object(Bucket=BUCKET, Key=key, Body=to_parquet_bytes(rows))
            print(f"wrote {len(rows):>5} rows -> s3://{BUCKET}/{key}", flush=True)
        if n_buf:
            c.commit(asynchronous=False)
        buf, n_buf, last = defaultdict(list), 0, time.time()

    try:
        while True:
            msg = c.poll(1.0)
            if msg is not None and not msg.error():
                row = json.loads(msg.value())
                row.update(kafka_partition=msg.partition(), kafka_offset=msg.offset(),
                           kafka_ts=msg.timestamp()[1], ingested_at=int(time.time() * 1000))
                buf[(TOPICS[msg.topic()], row["match_id"])].append(row)
                n_buf += 1
            if n_buf and (n_buf >= BATCH_MSGS or time.time() - last >= BATCH_SECONDS):
                flush()
    except KeyboardInterrupt:
        flush()
    finally:
        c.close()


if __name__ == "__main__":
    main()
