"""live_feed.py: one background Kafka consumer for the whole app, keeping the latest live.MatchState per match.

The page only takes a snapshot of the states, so a redraw never waits for Kafka. The consumer reads every topic from
the beginning with its own group (nothing is committed): live.route keeps only the latest replay of each match (by its
replay_id header), so a page opened in the middle of a replay still gets the score from the kick-off. It also reads
foot-live-stats, the 5-minute stats written by the streaming job (step 6), keeping the latest row per key.
"""
import json
import logging
import os
import threading
import uuid

import streamlit as st

import live

log = logging.getLogger(__name__)

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
        try:
            while True:
                for msg in consumer.consume(num_messages=1000, timeout=0.5):
                    if msg.error():
                        self.error = str(msg.error())
                        log.warning("kafka: %s", self.error)
                        continue
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
