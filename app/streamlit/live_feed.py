"""live_feed.py: one background Kafka consumer for the whole app, keeping the latest live.MatchState per match.

The page only takes a snapshot of the states, so a redraw never waits for Kafka. The consumer reads every topic from
the beginning with its own group (nothing is committed): live.apply drops the messages of older replays, so a page
opened in the middle of a replay still gets the score from the kick-off.
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


class Feed:
    def __init__(self, bootstrap: str):
        self._states: dict[str, live.MatchState] = {}
        self._lock = threading.Lock()
        self.messages = 0
        self.error: str | None = None
        threading.Thread(target=self._run, args=(bootstrap,), daemon=True, name="live-feed").start()

    def snapshot(self) -> dict[str, live.MatchState]:
        with self._lock:
            return dict(self._states)

    def _run(self, bootstrap: str) -> None:
        from confluent_kafka import Consumer

        consumer = Consumer({"bootstrap.servers": bootstrap, "group.id": f"live-page-{uuid.uuid4().hex[:8]}",
                             "auto.offset.reset": "earliest", "enable.auto.commit": False})
        consumer.subscribe(list(TOPIC_TABLE))
        try:
            while True:
                for msg in consumer.consume(num_messages=1000, timeout=0.5):
                    if msg.error():
                        self.error = str(msg.error())
                        log.warning("kafka: %s", self.error)
                        continue
                    self._apply(TOPIC_TABLE[msg.topic()], json.loads(msg.value()), msg.timestamp()[1])
        except Exception as exc:
            self.error = repr(exc)          # shown on the page; the thread then stops loudly
            raise
        finally:
            consumer.close()

    def _apply(self, table: str, rec: dict, kafka_ms: int) -> None:
        match_id = rec["match_id"]
        with self._lock:
            state = self._states.get(match_id) or live.MatchState(match_id)
            self._states[match_id] = live.apply(state, table, rec, kafka_ms)
            self.messages += 1


@st.cache_resource
def start_feed() -> Feed | None:
    """The app's single consumer, created at the first page view. None when KAFKA_BOOTSTRAP is not set."""
    bootstrap = os.getenv("KAFKA_BOOTSTRAP")
    return Feed(bootstrap) if bootstrap else None
