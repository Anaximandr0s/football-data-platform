"""live_feed.py: one background Kafka consumer for the whole app, keeping the latest live.MatchState per match.

The page only takes a snapshot of the states, so a redraw never waits for Kafka. The consumer reads every topic from
the beginning with its own group (nothing is committed): live.route keeps only the latest replay of each match (by its
replay_id header), so a page opened in the middle of a replay still gets the score from the kick-off. It also reads
foot-live-stats, the 5-minute stats written by the streaming job (step 6), keeping the latest row per key.

It also serves Prometheus metrics on METRICS_PORT: how far behind the end of each topic it is (no group offset is
committed, so a Kafka exporter cannot see it), and the live delay from Kafka to the app.
"""
import json
import logging
import os
import threading
import time
import uuid

import streamlit as st

import live

log = logging.getLogger(__name__)
METRICS_PORT = int(os.getenv("LIVE_METRICS_PORT", "9108"))
LAG_EVERY_S = 5
DELAY_BUCKETS = (0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 5, 10, 30)

# same names and defaults as ingestion/config.py (the app image does not ship the ingestion package)
TOPIC_TABLE = {os.getenv(f"KAFKA_TOPIC_{t.upper()}", f"foot-{t}"): t
               for t in ("tracking", "events", "ball", "players", "matches")}
LIVE_STATS_TOPIC = os.getenv("KAFKA_TOPIC_LIVE_STATS", "foot-live-stats")
REPLAY_HEADER = "replay_id"   # as ingestion/config.py


def replay_id_of(headers) -> str | None:
    for name, value in headers or []:
        if name == REPLAY_HEADER and value is not None:
            return value.decode()
    return None


class Feed:
    def __init__(self, bootstrap: str):
        self._states: dict[str, live.MatchState] = {}
        self._stats: dict[str, dict] = {}                 # key of foot-live-stats -> latest row
        self._lock = threading.Lock()
        self.messages = 0
        self.error: str | None = None
        self.caught_up = False      # before, it re-reads old replays: their delay says nothing about the live path
        self._metrics()
        threading.Thread(target=self._run, args=(bootstrap,), daemon=True, name="live-feed").start()

    def snapshot(self) -> dict[str, live.MatchState]:
        with self._lock:
            return dict(self._states)

    def stats(self, replay_id: str) -> list[dict]:
        """The latest foot-live-stats rows of one replay."""
        with self._lock:
            return [r for r in self._stats.values() if r.get("replay_id") == replay_id]

    def _run(self, bootstrap: str) -> None:
        from confluent_kafka import Consumer

        consumer = Consumer({"bootstrap.servers": bootstrap, "group.id": f"live-page-{uuid.uuid4().hex[:8]}",
                             "auto.offset.reset": "earliest", "enable.auto.commit": False})
        consumer.subscribe([*TOPIC_TABLE, LIVE_STATS_TOPIC])
        lag_at = 0.0
        try:
            while True:
                msgs = consumer.consume(num_messages=1000, timeout=0.5)
                if time.monotonic() - lag_at > LAG_EVERY_S:
                    self._lag(consumer)
                    lag_at = time.monotonic()
                for msg in msgs:
                    if msg.error():
                        self.error = str(msg.error())
                        log.warning("kafka: %s", self.error)
                        continue
                    if self.caught_up:
                        self._delay.labels(msg.topic()).observe(max(0.0, time.time() - msg.timestamp()[1] / 1000))
                    if msg.topic() == LIVE_STATS_TOPIC:
                        self._stat(msg.key().decode(), json.loads(msg.value()))
                        continue
                    self._apply(TOPIC_TABLE[msg.topic()], json.loads(msg.value()), msg.timestamp()[1],
                                replay_id_of(msg.headers()))
        except Exception as exc:
            self.error = repr(exc)          # shown on the page; the thread then stops loudly
            raise
        finally:
            consumer.close()

    def _metrics(self) -> None:
        from prometheus_client import CollectorRegistry, Gauge, Histogram, start_http_server

        registry = CollectorRegistry()
        self._lag_gauge = Gauge("football_live_consumer_lag_messages", "Messages the live page has not read yet",
                                ["topic"], registry=registry)
        self._delay = Histogram("football_live_delay_seconds", "From the Kafka timestamp to the live page",
                                ["topic"], buckets=DELAY_BUCKETS, registry=registry)
        start_http_server(METRICS_PORT, registry=registry)

    def _lag(self, consumer) -> None:
        from confluent_kafka import TopicPartition

        behind: dict[str, int] = {}
        for tp in consumer.assignment():
            low, high = consumer.get_watermark_offsets(tp, timeout=2)
            pos = consumer.position([TopicPartition(tp.topic, tp.partition)])[0].offset
            behind[tp.topic] = behind.get(tp.topic, 0) + (high - (pos if pos >= 0 else low))
        for topic, n in behind.items():
            self._lag_gauge.labels(topic).set(n)
        if behind and not self.caught_up and sum(behind.values()) == 0:
            self.caught_up = True

    def _apply(self, table: str, rec: dict, kafka_ms: int, replay_id: str | None) -> None:
        with self._lock:
            self._states = live.route(self._states, replay_id, table, rec, kafka_ms)
            self.messages += 1

    def _stat(self, key: str, rec: dict) -> None:
        with self._lock:
            self._stats[key] = rec


@st.cache_resource
def start_feed() -> Feed | None:
    """The app's single consumer, created at the first page view. None when KAFKA_BOOTSTRAP is not set."""
    bootstrap = os.getenv("KAFKA_BOOTSTRAP")
    return Feed(bootstrap) if bootstrap else None
