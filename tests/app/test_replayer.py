"""The Replay data (app/streamlit/replayer.py): the match payload, and the panel up to a second. Also: Live and Replay
draw the same second at the same place. No Streamlit, no DuckDB."""
import pandas as pd
from test_live import halves, run, second

import live
import replayer

PERIOD2 = 60


def frames(seconds, shift=0.0):
    """gold_replay_frames rows (Silver's frame) for the six players and the ball of tests/app/test_live.py: period 2
    is mirrored here by the contract's rule, x -> 105 - x and y -> 68 - y (HOME attacks toward x = 0 after the break)."""
    camera = {"H01": (5, 34), "H02": (30, 10), "H03": (50, 60), "A01": (100, 34), "A02": (70, 20), "A03": (60, 50)}
    rows = []
    for ts in seconds:
        mirror = ts >= PERIOD2
        for pid, (x, y) in camera.items():
            x, y = x + shift, y
            x, y = (105 - x, 68 - y) if mirror else (x, y)
            rows.append(dict(ts=ts, object_id=pid, object_type="player", team_id="HOME" if pid[0] == "H" else "AWAY",
                             x=min(max(x, 0.0), 105.0), y=y, z=None, speed_kmh=18.0 if pid == "H02" else None,
                             is_detected=pid != "A03", possession=None, home_space_share=0.5))
        rows.append(dict(ts=ts, object_id="ball", object_type="ball", team_id=None, x=-1.25 if ts == 1 else 52.5,
                         y=34.0, z=1.5 if ts == 1 else 0.11, speed_kmh=None, is_detected=None, possession="HOME" if ts < 2 else "AWAY",
                         home_space_share=0.6 if ts < 2 else 0.4))
    return pd.DataFrame(rows)


def test_live_and_replay_show_the_same_position_for_the_same_second():
    for ts, period, shift in ((0, 1, 0.0), (PERIOD2, 2, -40.0)):
        state = run(second(ts, period=period, shift=shift), halves())
        _, _, drawn_live = live.silver_frame(state)
        data = replayer.payload(frames([ts], shift=shift), "m1")
        for pid, (x, y, _) in drawn_live.items():
            assert replayer.position_at(data, ts, pid) == (x, y), (ts, pid)


def test_the_payload_holds_every_tracked_second_in_centimetres():
    data = replayer.payload(frames([0, 1, 3]), "m1")
    assert data["t"] == [0, 1, 3] and data["ids"] == ["A01", "A02", "A03", "H01", "H02", "H03"]
    assert data["xy"][0][:6] == [5250, 3400, 11, 10000, 3400, 1]        # ball (x, y, z), then A01 (x, y, detected)
    assert data["xy"][1][2] == 150                                       # the ball 1.5 m high
    assert replayer.position_at(data, 1, "ball") == (-1.25, 34.0)        # the ball may leave the pitch
    assert replayer.position_at(data, 0, "A03") == (60.0, 50.0) and data["xy"][0][replayer.BALL + 3 * 2 + 2] == 0
    assert replayer.position_at(data, 2, "H01") is None                 # a camera gap: no second, nothing drawn


def test_the_panel_only_knows_what_happened_up_to_the_second_watched():
    f = frames([0, 1, 2, 3])
    assert replayer.possession_until(f, 1) == (2, 0) and replayer.possession_until(f, 3) == (2, 2)
    assert replayer.space_now(f, 1) == 0.6 and replayer.space_now(f, 10) == 0.4
    stats = replayer.player_until(f, "H02", 2)
    assert stats.tracked_seconds == 3 and round(stats.distance_m, 6) == round(3 * 18 / 3.6, 6)
    goal_list = [[1, "HOME", "1' A"], [3, "AWAY", "1' B"]]
    assert replayer.score_at(goal_list, 0) == (0, 0) and replayer.score_at(goal_list, 3) == (1, 1)
    timeline = pd.DataFrame([dict(team_id=t, window_index=w, window_label=f"{5 * w}-{5 * w + 5}", window_end_ts=e,
                                  possession_greyed=False, possession_share=0.5, passes=1,
                                  xthreat_successful_passes=0.1)
                             for w, e in ((0, 300), (1, 600)) for t in ("HOME", "AWAY")])
    assert list(replayer.windows_until(timeline, 299).window_label) == ["0-5"]       # second 299 ends window 0
    assert list(replayer.windows_until(timeline, 298).window_label) == []
    assert list(replayer.windows_until(timeline, 700).window_label) == ["5-10", "0-5"]


def test_the_clock_labels_come_from_the_football_clock():
    labels = replayer.clock_labels(0, 3000, 0, 2900)
    assert labels[0] == "00:00" and labels[2700] == "45:00" and labels[2760] == "45:00 +1:00" and labels[2900] == "45:00"


def test_goals_change_the_score_when_the_ball_is_in_and_events_have_a_caption():
    events = pd.DataFrame([
        dict(ts=100, goal_ts=104, period=1, type="goal", team_id="AWAY", player_short_name="A. Goodwin"),
        dict(ts=90, goal_ts=None, period=1, type="shot", team_id="HOME", player_short_name="S. Klein"),
        dict(ts=95, goal_ts=None, period=1, type="pass", team_id="HOME", player_short_name="S. Klein")])
    goal_list = replayer.goals(events, 0, 2900)
    assert goal_list == [[104, "AWAY", "2' A. Goodwin", "A. Goodwin"]]               # the minute of the attack
    assert replayer.score_at(goal_list, 103) == (0, 0) and replayer.score_at(goal_list, 104) == (0, 1)
    assert replayer.shots(events, 0, 2900) == [[90, "HOME", "2' S. Klein"]]
    assert replayer.key_events(events, {"HOME": "Reds", "AWAY": "Blues"}, 0, 2900) == [
        [90, "Shot - S. Klein (Reds) - 2'"], [104, "Goal - A. Goodwin (Blues) - 2'"]]
