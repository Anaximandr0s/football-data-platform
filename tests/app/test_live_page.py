"""The Live match page, headless (streamlit.testing): a fake feed stands in for Kafka."""
import time
from pathlib import Path

import pytest

import live
import live_feed

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
PAGE = str(Path(__file__).resolve().parents[2] / "app" / "streamlit" / "pages" / "0_Live_match.py")
MATCH = {"match_id": "m1", "home_team": "Home FC", "away_team": "Away FC", "home_color": "#ff0000",
         "away_color": "#0000ff", "p2_end_ts": 6000, "home_side_p1": "left_to_right", "home_side_p2": "right_to_left"}


class FakeFeed:
    def __init__(self, states):
        self._states, self.messages, self.error = states, 1234, None

    def snapshot(self):
        return dict(self._states)


def state_at(last_ms: int) -> live.MatchState:
    """A replay at x5 whose latest tracked second (ts 600) was sent at `last_ms`; HOME scored at ts 300."""
    start = last_ms - 600 * 200
    s = live.apply(live.MatchState("m1"), "matches", MATCH, start)
    for i in range(22):
        team = "HOME" if i < 11 else "AWAY"
        pid = f"{team[0]}{i % 11 + 1:02d}"
        s = live.apply(s, "players", {"match_id": "m1", "player_id": pid, "team_id": team, "shirt_number": i % 11 + 1,
                                      "short_name": f"P. {pid}", "position": "GK" if i % 11 == 0 else "CM"}, start + 1)
        for ts in (0, 600):
            s = live.apply(s, "tracking", {"match_id": "m1", "player_id": pid, "ts": ts, "period": 1,
                                           "x": 10.0 + i * 4, "y": 5.0 + (i % 11) * 5, "is_detected": True},
                           start + ts * 200)
    s = live.apply(s, "ball", {"match_id": "m1", "ts": 600, "period": 1, "x": 50.0, "y": 30.0, "z": 0.0,
                               "possession": "HOME"}, last_ms)
    return live.apply(s, "events", {"match_id": "m1", "event_id": "m1-e00001", "ts": 300, "type": "goal",
                                    "team_id": "HOME", "player_id": "H09"}, start + 300 * 200)


def page(monkeypatch, feed):
    monkeypatch.setattr(live_feed, "start_feed", lambda: feed)
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return at


def texts(at) -> str:
    return " ".join([m.value for m in at.markdown] + [c.value for c in at.caption] + [i.value for i in at.info])


def test_live_page_shows_score_clock_event_possession_and_shape(monkeypatch):
    # sent a minute "from now", so the page sees it as just arrived however slow the test machine is
    at = page(monkeypatch, FakeFeed({"m1": state_at(int(time.time() * 1000) + 60_000)}))
    shown = texts(at)
    assert "Home FC 1 - 0 Away FC" in shown
    assert "10:00" in shown and "Period 1" in shown
    assert "Goal, 6', Home FC (P. H09)" in shown
    assert "Possession 100% - 0%" in shown
    assert len(at.dataframe) == 1                                         # team shape of the current second
    assert "FOO-08" in shown and "camera off the pitch" not in shown


def test_live_page_says_the_camera_is_off_during_a_gap(monkeypatch):
    at = page(monkeypatch, FakeFeed({"m1": state_at(int(time.time() * 1000) - 10_000)}))
    assert "No tracking: camera off the pitch" in texts(at)
    assert len(at.dataframe) == 0                                         # no shape from frozen positions


def test_live_page_waits_for_a_replay_and_needs_kafka(monkeypatch):
    assert "make replay" in texts(page(monkeypatch, FakeFeed({})))
    at = page(monkeypatch, None)
    assert "KAFKA_BOOTSTRAP" in at.error[0].value
