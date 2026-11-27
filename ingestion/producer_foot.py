"""producer_foot.py (step 3): replay a prepared match into Kafka at an adjustable speed.

    python -m ingestion.producer_foot --match m001 --speed 60
    python -m ingestion.producer_foot --match m001 --speed 60 --dry-run    # no Kafka

Reads data/prepared/<match>/ (written by ingest_foot.py). Needs the stack (make up) unless --dry-run.
x1 = real time (1 tick = 1 match second = 22 positions); x60 = 60 ticks per second.
Reference tables (matches, players) are sent first, then the live stream.

  topic          key        content
  foot-matches   match_id   one message: score, periods, attack directions
  foot-players   player_id  one message per player (sent at the start)
  foot-tracking  player_id  one message per player per second (order kept per player)
  foot-events    match_id   one message per game action
  foot-ball      match_id   one message per second

Every message of one run carries the Kafka header replay_id = "<match>-<UTC start>" (m001-20261116T101503Z): the
streaming job and the live page keep two replays of the same match apart with it, and bronze stores it.
Replaying twice doubles the bronze data (at-least-once delivery): Silver deduplicates.
The process exits with an error if a message could not be delivered.
"""
import argparse
import datetime as dt
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd

from ingestion import replay_ids
from ingestion.config import KAFKA_BOOTSTRAP, KEYS, PREPARED_DIR, REPLAY_HEADER, TOPICS


def read_records(path: Path) -> list[dict]:
    """Parquet -> list of JSON-safe dicts (NaN becomes null)."""
    return json.loads(pd.read_parquet(path).to_json(orient="records"))


def by_ts(records: list[dict]) -> dict:
    """Group records by their `ts` (match second)."""
    out = defaultdict(list)
    for r in records:
        out[r["ts"]].append(r)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--match", required=True, help="prepared match id, e.g. m001")
    ap.add_argument("--speed", type=float, default=30.0, help="1 to 60")
    ap.add_argument("--start", type=int, default=0, help="start at this match second")
    ap.add_argument("--data-dir", type=Path, default=PREPARED_DIR)
    ap.add_argument("--bootstrap", default=KAFKA_BOOTSTRAP)
    ap.add_argument("--dry-run", action="store_true", help="do not contact Kafka")
    a = ap.parse_args()
    if not 1 <= a.speed <= 60:
        ap.error("--speed must be between 1 and 60")

    mdir = a.data_dir / a.match
    if not mdir.exists():
        sys.exit(f"{mdir} not found: run  python -m ingestion.ingest_foot  first")
    reference = {t: read_records(mdir / f"{t}.parquet") for t in ("matches", "players")}
    live = {t: by_ts(read_records(mdir / f"{t}.parquet")) for t in ("tracking", "events", "ball")}

    first = min(set().union(*live.values()))
    # started after the first second: a partial replay, live only (ingestion/replay_ids.py)
    replay_id = replay_ids.make(a.match, dt.datetime.now(dt.UTC), partial=a.start > first)
    headers = [(REPLAY_HEADER, replay_id.encode())]
    print(f"replay_id={replay_id}", flush=True)
    errors: list[str] = []
    counts: dict[str, int] = defaultdict(int)
    producer = None
    if not a.dry_run:
        from confluent_kafka import Producer
        producer = Producer({"bootstrap.servers": a.bootstrap, "linger.ms": 20,
                             "enable.idempotence": True,
                             "log_level": 3})   # librdkafka errors only (hides a harmless startup warning)

    def on_delivery(err, _msg) -> None:
        if err is not None:
            errors.append(str(err))

    def send(table: str, rec: dict) -> None:
        counts[table] += 1
        if producer is None:
            return
        value = json.dumps(rec, allow_nan=False)
        while True:
            try:
                producer.produce(TOPICS[table], key=str(rec[KEYS[table]]), value=value, headers=headers,
                                 on_delivery=on_delivery)
                break
            except BufferError:          # local queue full: let the client drain it
                producer.poll(0.5)
        producer.poll(0)

    for table, records in reference.items():
        for rec in records:
            send(table, rec)

    all_ts = set().union(*live.values())
    start_ts, last_ts = max(first, a.start), max(all_ts)
    t0 = time.perf_counter()
    for ts in range(start_ts, last_ts + 1):
        delay = t0 + (ts - start_ts) / a.speed - time.perf_counter()   # absolute schedule: no drift
        if delay > 0:
            time.sleep(delay)
        for table, source in live.items():
            for rec in source.get(ts, []):
                send(table, rec)
        if ts % 300 == 0:
            print(f"minute {ts // 60:>3} | " + " ".join(f"{k}={v}" for k, v in counts.items()),
                  flush=True)

    left = producer.flush(60) if producer else 0
    print(f"done in {time.perf_counter() - t0:.1f}s | " + " ".join(f"{k}={v}" for k, v in counts.items()))
    if errors or left:
        sys.exit(f"FAILED: {len(errors)} delivery errors (first: {errors[:1]}), {left} messages not flushed")


if __name__ == "__main__":
    main()