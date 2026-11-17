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
