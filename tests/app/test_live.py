"""The live state (app/streamlit/live.py): messages in, state out. No Kafka, no Streamlit."""
import live

MATCH = {"match_id": "m1", "home_team": "Home FC", "away_team": "Away FC", "home_color": "#ff0000",
         "away_color": "#0000ff", "p2_end_ts": 100, "home_side_p1": "left_to_right", "home_side_p2": "right_to_left"}
T0 = 1_000_000          # Kafka time of the replay start, ms
PACE = 200              # ms per match second: a replay at x5


def player(pid, team, number, position="CM"):
    return {"match_id": "m1", "player_id": pid, "team_id": team, "short_name": f"P. {pid}",
            "shirt_number": number, "position": position}


def run(messages, state=None):
    """messages: (table, record, kafka_ms)."""
    state = state or live.MatchState("m1")
    for table, rec, ms in messages:
        state = live.apply(state, table, rec, ms)
    return state


def kickoff(start=T0):
    players = [player("H01", "HOME", 1, "GK"), player("H02", "HOME", 4), player("H03", "HOME", 9),
               player("A01", "AWAY", 1, "GK"), player("A02", "AWAY", 5), player("A03", "AWAY", 10)]
    return [("matches", MATCH, start)] + [("players", p, start + 1) for p in players]


def second(ts, start=T0, period=1, possession=None, shift=0.0):
    """One tracked second: six players and the ball, sent at the replay pace."""
    ms = start + ts * PACE
    xy = {"H01": (5, 34), "H02": (30, 10), "H03": (50, 60), "A01": (100, 34), "A02": (70, 20), "A03": (60, 50)}
    msgs = [("tracking", {"match_id": "m1", "player_id": pid, "ts": ts, "period": period, "x": x + shift, "y": y,
                          "is_detected": pid != "A03"}, ms) for pid, (x, y) in xy.items()]
    msgs.append(("ball", {"match_id": "m1", "ts": ts, "period": period, "x": 52.5, "y": 34.0, "z": 0.0,
                          "possession": possession}, ms))
    return msgs


def event(eid, ts, kind, team, pid, start=T0):
    return ("events", {"match_id": "m1", "event_id": eid, "ts": ts, "type": kind, "team_id": team,
                       "player_id": pid}, start + ts * PACE)


def test_positions_show_the_latest_complete_second(monkeypatch):
    monkeypatch.setattr(live, "FULL_FRAME", 6)
    s = run(kickoff() + second(0) + second(1, shift=1.0))
    ts, positions = live.current_frame(s)
    assert ts == 1 and positions["H02"] == (31.0, 10, True) and positions["A03"][2] is False
    partial = live.apply(s, "tracking", {"match_id": "m1", "player_id": "H01", "ts": 2, "period": 1,
                                         "x": 0.0, "y": 0.0, "is_detected": True}, T0 + 2 * PACE)
    assert live.current_frame(partial)[0] == 1          # second 2 has 1 of 6 players: keep showing second 1
    assert sorted(partial.frames) == [1, 2]             # only two seconds are kept


def test_score_after_each_goal_and_the_event_line():
    s = run(kickoff() + second(0))
    assert live.score(s) == (0, 0) and live.event_line(s) is None
    s = run([event("m1-e00001", 30, "goal", "HOME", "H03")], s)
    assert live.score(s) == (1, 0)
    assert live.event_line(s) == "Goal, 1', Home FC (P. H03)"
    s = run([event("m1-e00002", 70, "goal", "AWAY", "A03"), event("m1-e00003", 95, "goal", "AWAY", "A02")], s)
    assert live.score(s) == (1, 2)
    assert live.event_line(s) == "Goal, 2', Away FC (P. A02)"
    s = run([event("m1-e00003", 95, "goal", "AWAY", "A02")], s)        # a duplicate never counts twice
    assert live.score(s) == (1, 2)


def test_passes_pressures_and_runs_never_become_the_event_line():
    s = run(kickoff() + [event("m1-e00001", 10, "shot", "HOME", "H03"), event("m1-e00002", 11, "pass", "HOME", "H02"),
                         event("m1-e00003", 12, "pressure", "AWAY", "A02"), event("m1-r00001", 13, "run", "HOME", "H03")])
    assert live.event_line(s) == "Shot, 1', Home FC (P. H03)"


def test_possession_share_and_current_owner():
    s = run(kickoff() + second(0, possession="HOME") + second(1, possession="HOME") + second(2, possession="AWAY")
            + second(3, possession=None))
    home, away, seconds = live.possession_share(s)
    assert (round(home, 3), round(away, 3), seconds) == (0.667, 0.333, 3)    # the dead-ball second is not counted
    assert live.current_owner(s) is None
    assert live.possession_share(run(kickoff())) is None


def test_camera_gap_then_stalled_then_full_time():
    s = run(kickoff() + second(0) + second(10))
    last_ms = T0 + 10 * PACE
    assert live.status(s, last_ms + 300) == "live"
    assert live.status(s, last_ms + 5 * PACE + 500) == "gap"           # nothing for 5 match seconds
    assert live.clock(s, last_ms + 5 * PACE) == 15                       # the clock runs on through the gap
    assert live.status(s, last_ms + 400 * PACE) == "stalled"
    end = run(second(100), s)
    assert live.status(end, T0 + 100 * PACE + 60_000) == "full_time"
    assert live.clock(end, T0 + 100 * PACE + 60_000) == 100              # never past the last second of the match


def test_an_older_replay_is_ignored_even_when_its_messages_arrive_late():
    first = run(kickoff(T0) + second(0, T0) + [event("m1-e00001", 30, "goal", "HOME", "H03", T0)])
    t1 = T0 + 1_000_000
    # the new replay's goal and positions arrive BEFORE its matches row (topics are not ordered with each other)
    s = run([event("m1-e00009", 5, "goal", "AWAY", "A02", t1)] + second(3, t1), first)
    s = run(kickoff(t1), s)
    assert live.score(s) == (0, 1)                                      # the old HOME goal is gone, the new one kept
    assert live.current_frame(s)[0] == 3
    late_old = run([event("m1-e00002", 40, "goal", "HOME", "H02", T0)] + second(50, T0), s)
    assert live.score(late_old) == (0, 1) and live.current_frame(late_old)[0] == 3


def test_team_shape_uses_outfield_players_of_the_current_second():
    s = run(kickoff() + second(0))
    shape = live.team_shape(s, live.current_frame(s)[1])
    assert shape == {"HOME": (50.0, 20.0), "AWAY": (30.0, 10.0)}         # goalkeepers left out


def test_direction_of_attack_follows_the_period():
    s = run(kickoff() + second(0))
    assert live.home_attacks_right(s) is True
    assert live.home_attacks_right(run(second(60, period=2), s)) is False
