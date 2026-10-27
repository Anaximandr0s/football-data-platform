"""producer_foot.py: replay a generated match into Kafka at an adjustable speed (FOO-02).

  python -m data_gen.producer_foot --match m001 --speed 30
  python -m data_gen.producer_foot --match m001 --speed 60 --dry-run   # no Kafka needed

Speed x1 = real time (one tick of 22 positions per second); x60 = 60 ticks per second.
Tracking key = player_id (ordering per player). Events key = match_id.
"""
import argparse
import json
import os
import time
from pathlib import Path

import pandas as pd

from data_gen.common import GENERATED_DIR


def build_ticks(match_dir: Path):
    """Yield (ts, [tracking messages], [event messages]) for every second of the match."""
    tr = pd.read_parquet(match_dir / "tracking.parquet")
    ev = pd.read_parquet(match_dir / "events.parquet")
    tr_by = {ts: g.to_dict("records") for ts, g in tr.groupby("ts")}
    ev_by = {ts: g.to_dict("records") for ts, g in ev.groupby("ts")}
    for ts in range(int(tr["ts"].min()), int(tr["ts"].max()) + 1):
        yield ts, tr_by.get(ts, []), ev_by.get(ts, [])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--match", default="m001")
    ap.add_argument("--speed", type=float, default=30.0, help="1 to 60")
    ap.add_argument("--start", type=int, default=0, help="start at this second")
    ap.add_argument("--data-dir", type=Path, default=GENERATED_DIR)
    ap.add_argument("--bootstrap", default=os.getenv("KAFKA_EXTERNAL_BOOTSTRAP", "localhost:29092"))
    ap.add_argument("--topic-tracking", default=os.getenv("KAFKA_TOPIC_TRACKING", "foot-tracking"))
    ap.add_argument("--topic-events", default=os.getenv("KAFKA_TOPIC_EVENTS", "foot-events"))
    ap.add_argument("--dry-run", action="store_true", help="do not contact Kafka")
    a = ap.parse_args()
    if not 1 <= a.speed <= 60:
        ap.error("--speed must be between 1 and 60")

    producer = None
    if not a.dry_run:
        from confluent_kafka import Producer
        producer = Producer({"bootstrap.servers": a.bootstrap, "linger.ms": 20,
                             "enable.idempotence": True})

    sent_t = sent_e = 0
    t0 = time.perf_counter()
    for ts, trs, evs in build_ticks(a.data_dir / a.match):
        if ts < a.start:
            continue
        due = t0 + (ts - a.start) / a.speed          # absolute schedule: no drift
        delay = due - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        for m in trs:
            if producer:
                producer.produce(a.topic_tracking, key=m["player_id"], value=json.dumps(m))
            sent_t += 1
        for m in evs:
            if producer:
                producer.produce(a.topic_events, key=m["match_id"], value=json.dumps(m))
            sent_e += 1
        if producer:
            producer.poll(0)
        if ts % 300 == 0:
            print(f"minute {ts // 60:>3} | tracking={sent_t} events={sent_e}", flush=True)
    if producer:
        producer.flush(30)
    print(f"done: {sent_t} tracking + {sent_e} event messages in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
