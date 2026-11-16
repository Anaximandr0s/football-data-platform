"""The Live match page, headless (streamlit.testing): a fake feed stands in for Kafka."""
import time
from pathlib import Path

import pytest

import live
import live_feed

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
PAGE = str(Path(__file__).resolve().parents[2] / "app" / "streamlit" / "sections" / "live_match.py")
MATCH = {"match_id": "m1", "home_team": "Home FC", "away_team": "Away FC", "home_color": "#ff0000",
         "away_color": "#0000ff", "p2_end_ts": 6000, "home_side_p1": "left_to_right", "home_side_p2": "right_to_left"}


class FakeFeed:
    def __init__(self, states):
        self._states, self.messages, self.error = states, 1234, None

    def snapshot(self):
        return dict(self._states)

    def stats(self, replay_id):
        return [r for r in getattr(self, "rows", []) if r["replay_id"] == replay_id]


def state_at(last_ms: int) -> live.MatchState:
    """A replay at x5 whose latest tracked second (ts 600) was sent at `last_ms`; HOME scored at ts 300."""
    start = last_ms - 600 * 200
    s = live.apply(live.MatchState("m1", replay_id="m1-20261116T101503Z"), "matches", MATCH, start)
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
    assert "make streaming" in shown and "camera off the pitch" not in shown        # no window yet


def test_live_page_says_the_camera_is_off_during_a_gap(monkeypatch):
    at = page(monkeypatch, FakeFeed({"m1": state_at(int(time.time() * 1000) - 10_000)}))
    assert "No tracking: camera off the pitch" in texts(at)
    assert len(at.dataframe) == 0                                         # no shape from frozen positions


def through_router(monkeypatch, feed) -> AppTest:
    """The page as the site serves it: st.page_link needs the router's menu."""
    monkeypatch.setattr(live_feed, "start_feed", lambda: feed)
    at = AppTest.from_file(str(Path(PAGE).parents[1] / "app.py"), default_timeout=60).run()
    at.switch_page("sections/live_match.py").run()
    assert not at.exception, at.exception
    return at


def test_live_page_says_no_match_is_live_and_links_to_replay(monkeypatch, app_env):
    at = through_router(monkeypatch, FakeFeed({}))
    assert "No match live right now." in [i.value for i in at.info]
    assert "make replay" in texts(at)
    finished = live.apply(state_at(int(time.time() * 1000)), "tracking",
                          {"match_id": "m1", "player_id": "H01", "ts": 6000, "period": 2, "x": 1.0, "y": 1.0,
                           "is_detected": True}, int(time.time() * 1000))
    assert "No match live right now." in [i.value for i in through_router(monkeypatch, FakeFeed({"m1": finished})).info]


def test_live_page_lists_what_plays_and_opens_the_sidebar_match(monkeypatch):
    now = int(time.time() * 1000) + 60_000
    monkeypatch.setattr(live_feed, "start_feed", lambda: FakeFeed({"m1": state_at(now), "m2": state_at(now)}))
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["match_id"] = "m2"
    at.run()
    assert not at.exception and "NOW PLAYING" in texts(at)
    assert at.selectbox[0].value == "m2" and len(at.selectbox[0].options) == 2


def test_live_page_needs_kafka(monkeypatch):
    at = page(monkeypatch, None)
    assert "KAFKA_BOOTSTRAP" in at.error[0].value


def test_live_page_shows_the_stats_so_far_of_the_clicked_player(monkeypatch):
    monkeypatch.setattr(live_feed, "start_feed", lambda: FakeFeed({"m1": state_at(int(time.time() * 1000) + 60_000)}))
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["live_player"] = {"m1": "H09"}         # what a click on the pitch stores
    at.run()
    assert not at.exception
    assert "SELECTED PLAYER" in texts(at) and "P. H09" in texts(at)
    panel = texts(at)
    assert "<b>0.00 km</b>" in panel and "<span>Sprints</span><b>0</b>" in panel     # two seconds, no speed sent
    assert "<b>not yet</b>" in panel


def test_live_page_shows_the_5_minute_windows_of_the_streaming_job(monkeypatch):
    feed = FakeFeed({"m1": state_at(int(time.time() * 1000) + 60_000)})
    win = {"replay_id": "m1-20261116T101503Z", "match_id": "m1", "window_size": 300, "kind": "team"}
    feed.rows = [{**win, "window_index": 0, "window_label": "0-5", "team_id": "HOME", "possession_share": 0.6,
                  "possession_greyed": False, "ppp": 1.2, "ppp_greyed": False, "complete": True},
                 {**win, "window_index": 0, "window_label": "0-5", "team_id": "AWAY", "possession_share": 0.4,
                  "possession_greyed": False, "ppp": 0.9, "ppp_greyed": True, "complete": True},
                 {**win, "window_index": 1, "window_label": "5-10", "team_id": "HOME", "possession_share": 0.5,
                  "possession_greyed": True, "ppp": None, "ppp_greyed": True, "complete": False},
                 {**win, "window_index": 1, "window_label": "5-10", "team_id": "AWAY", "possession_share": 0.5,
                  "possession_greyed": True, "ppp": None, "ppp_greyed": True, "complete": False},
                 {**win, "kind": "player", "window_index": 1, "player_id": "H09", "team_id": "HOME",
                  "tracked_seconds": 120, "distance_m": 300.0, "max_speed_kmh": 28.4},
                 {**win, "replay_id": "m1-20261115T090000Z", "window_index": 5, "window_label": "25-30",
                  "team_id": "HOME", "complete": True}]                          # an older replay: never shown
    at = page(monkeypatch, feed)
    table = at.dataframe[-1].value
    assert list(table.minutes) == ["5-10'", "0-5'"] and list(table.status) == ["in progress", "complete"]
    assert list(table.iloc[:, 2]) == ["-", "60% - 40%"] and list(table.iloc[:, 3]) == ["-", "1.20"] and list(table.iloc[:, 4]) == ["-", "-"]
    assert "P. H09 150 m/min" in texts(at) and "top 28" not in texts(at)
