"""live_feed: the lag the live page reports to Prometheus, and when its delays start to count."""
import pytest

pytest.importorskip("confluent_kafka")
from confluent_kafka import TopicPartition  # noqa: E402
from prometheus_client import CollectorRegistry, Gauge  # noqa: E402

import live_feed  # noqa: E402


class FakeConsumer:
    def __init__(self, ends: dict, positions: dict):
        self.ends, self.positions = ends, positions        # (topic, partition) -> (low, high) / offset

    def assignment(self):
        return [TopicPartition(t, p) for t, p in self.ends]

    def get_watermark_offsets(self, tp, timeout):
        return self.ends[(tp.topic, tp.partition)]

    def position(self, tps):
        return [TopicPartition(tp.topic, tp.partition, self.positions[(tp.topic, tp.partition)]) for tp in tps]


def feed():
    f = live_feed.Feed.__new__(live_feed.Feed)          # no thread, no HTTP server
    registry = CollectorRegistry()
    f._lag_gauge = Gauge("lag", "lag", ["topic"], registry=registry)
    f.caught_up = False
    return f, registry


def test_the_lag_adds_the_partitions_of_a_topic_and_a_partition_never_read_counts_from_its_start():
    f, registry = feed()
    f._lag(FakeConsumer({("foot-tracking", 0): (0, 100), ("foot-tracking", 1): (10, 50), ("foot-ball", 0): (0, 5)},
                        {("foot-tracking", 0): 90, ("foot-tracking", 1): -1001, ("foot-ball", 0): 5}))
    assert registry.get_sample_value("lag", {"topic": "foot-tracking"}) == 10 + 40
    assert registry.get_sample_value("lag", {"topic": "foot-ball"}) == 0
    assert not f.caught_up


def test_delays_start_to_count_once_every_topic_is_read_to_its_end():
    f, _ = feed()
    f._lag(FakeConsumer({("foot-ball", 0): (0, 5)}, {("foot-ball", 0): 5}))
    assert f.caught_up
