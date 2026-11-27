"""live_feed: the lag the live page reports to Prometheus, and when its delays start to count."""
import pytest

pytest.importorskip("prometheus_client")
from prometheus_client import CollectorRegistry, Gauge  # noqa: E402

import live_feed  # noqa: E402


def test_the_lag_adds_the_partitions_of_a_topic_and_a_partition_never_read_counts_from_its_start():
    ends = {("foot-tracking", 0): (0, 100), ("foot-tracking", 1): (10, 50), ("foot-ball", 0): (0, 5)}
    read = {("foot-tracking", 0): 90, ("foot-ball", 0): 5}                       # partition 1 not read yet
    assert live_feed.lag_by_topic(ends, read) == {"foot-tracking": 10 + 40, "foot-ball": 0}


def feed():
    f = live_feed.Feed.__new__(live_feed.Feed)          # no threads, no HTTP server
    registry = CollectorRegistry()
    f._lag_gauge = Gauge("lag", "lag", ["topic"], registry=registry)
    f.caught_up = False
    return f, registry


def test_delays_start_to_count_once_every_topic_is_read_to_its_end():
    f, registry = feed()
    f._record_lag({"foot-tracking": 3, "foot-ball": 0})
    assert not f.caught_up and registry.get_sample_value("lag", {"topic": "foot-tracking"}) == 3
    f._record_lag({"foot-tracking": 0, "foot-ball": 0})
    assert f.caught_up


def test_the_reading_loop_never_asks_the_broker_for_the_lag():
    import inspect
    source = inspect.getsource(live_feed.Feed._run)
    assert "get_watermark_offsets" not in source and "position(" not in source


class Broker:
    """confluent_kafka.Consumer over a fixed list of messages, then an idle topic."""

    def __init__(self, messages):
        self.messages = list(messages)

    def __call__(self, _conf):
        return self

    def subscribe(self, _topics):
        pass

    def consume(self, num_messages, timeout):
        import time
        if not self.messages:
            time.sleep(timeout)
        out, self.messages = self.messages, []
        return out

    def list_topics(self, timeout):
        from types import SimpleNamespace
        return SimpleNamespace(topics={"foot-matches": SimpleNamespace(partitions={0: None})})

    def get_watermark_offsets(self, _tp, timeout):
        return 0, 0

    def close(self):
        pass


def message(topic, offset, value, key=None, error=None):
    import json
    from types import SimpleNamespace
    return SimpleNamespace(error=lambda: error, topic=lambda: topic, partition=lambda: 0, offset=lambda: offset,
                           timestamp=lambda: (1, 1_000), key=lambda: key, value=lambda: json.dumps(value).encode(),
                           headers=lambda: [("replay_id", b"m1-20261127T100000Z")])


def test_the_feed_keeps_each_matchs_latest_replay_and_the_live_stats(monkeypatch):
    import time

    import confluent_kafka

    broker = Broker([message("foot-matches", 0, {"match_id": "m1", "p1_start_ts": 0, "p2_end_ts": 90}),
                     message("foot-ball", 0, None, error="partition EOF"),
                     message("foot-live-stats", 4, {"replay_id": "m1-20261127T100000Z", "kind": "team"}, key=b"k1")])
    monkeypatch.setattr(confluent_kafka, "Consumer", broker)
    monkeypatch.setattr(live_feed, "METRICS_PORT", 0)
    monkeypatch.setattr(live_feed, "LAG_EVERY_S", 0.01)
    f = live_feed.Feed("kafka:9092")
    deadline = time.time() + 5
    while not (f.stats("m1-20261127T100000Z") and f.caught_up) and time.time() < deadline:
        time.sleep(0.01)
    assert f.snapshot()["m1"].replay_id == "m1-20261127T100000Z" and f.messages == 1
    assert f.stats("m1-20261127T100000Z") == [{"replay_id": "m1-20261127T100000Z", "kind": "team"}]
    assert f.caught_up and f.error == "partition EOF"


def test_without_a_bootstrap_there_is_no_feed(monkeypatch):
    monkeypatch.delenv("KAFKA_BOOTSTRAP", raising=False)
    assert live_feed.start_feed.__wrapped__() is None
