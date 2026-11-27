"""The rows of foot-live-stats (spark/streaming/rows.py): Gold's formulas, full values, and the completion rule."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app" / "streamlit"))  # clock.py, as the job ships it
from spark.streaming import rows  # noqa: E402

M001 = {"p1_start_ts": 0, "p1_end_ts": 2890, "p2_start_ts": 2899, "p2_end_ts": 6025}


def team_agg(window_index, last_ts, **counts):
    base = {
        f"{t}_{k}": 0
        for t in ("home", "away")
        for k in ("possession", "passes", "da", "da_own", "da_middle", "da_final")
    }
    return {
        "replay_id": "m001-20261116T101503Z",
        "match_id": "m001",
        "window_index": window_index,
        "last_ts": last_ts,
        **M001,
        **base,
        **counts,
    }


def test_team_rows_use_the_formulas_and_thresholds_of_gold():
    home, away = rows.team_5min(
        team_agg(9, 2800, home_possession=40, away_possession=10, home_passes=30, away_passes=8, home_da=6, away_da=12)
    )
    assert (home["window_label"], home["window_start_ts"], home["window_end_ts"], home["window_seconds"]) == (
        "45+",
        2700,
        2891,
        191,
    )
    assert (home["possession_seconds"], home["known_seconds"], home["possession_share"]) == (40, 50, 0.8)
    assert home["possession_greyed"] is True  # 50 known seconds < 60
    assert (home["ppp"], home["ppp_greyed"]) == (0.75, True)  # 6 actions / 8 AWAY passes, under 10
    assert (away["opponent_passes"], away["ppp"], away["ppp_greyed"]) == (30, 0.4, False)


def test_pressing_and_player_rows():
    home, _ = rows.team_15min(team_agg(4, 3500, home_da=20, home_da_final=5, away_passes=25))
    assert (home["window_label"], home["ppp"], home["high_press_share"]) == ("45-60", 0.8, 0.25)
    p = rows.player_5min(
        {
            "replay_id": "r",
            "match_id": "m001",
            "player_id": "H09",
            "team_id": "HOME",
            "window_index": 10,
            "last_ts": 3000,
            **M001,
            "tracked_seconds": 150,
            "distance_m": 512.3456,
            "sprint_seconds": 7,
            "max_speed_kmh": 31.234,
        }
    )
    assert (p["window_label"], p["coverage"], p["distance_m"], p["max_speed_kmh"]) == ("45-50", 0.5, 512.3, 31.23)
    assert rows.key(p) == "r|m001|300|10|H09"


def test_a_window_is_complete_after_its_end_plus_10_seconds_or_at_the_last_second():
    row = rows.team_5min(team_agg(0, 290))[0]  # 0-5', ends at ts 300 (exclusive)
    assert not rows.is_complete(row, 309) and rows.is_complete(row, 310)
    last = rows.team_5min(team_agg(19, 6025))[0]  # 90+: the end of the match
    assert rows.is_complete(last, 6025)


def test_merge_sends_full_values_and_completes_windows_left_behind():
    store: dict = {}
    first = rows.merge(store, rows.team_5min(team_agg(0, 290, home_passes=10)), now_ms=1)
    assert [r["complete"] for r in first] == [False, False] and first[0]["passes"] == 10
    again = rows.merge(store, rows.team_5min(team_agg(0, 299, home_passes=12)), now_ms=2)  # full value, not +2
    assert again[0]["passes"] == 12 and len(store) == 2
    later = rows.merge(store, rows.team_5min(team_agg(1, 320)), now_ms=3)  # tracking reaches 0-5' end + 10 s
    done = {(r["window_index"], r["team_id"]): r["complete"] for r in later}
    assert done == {(1, "HOME"): False, (1, "AWAY"): False, (0, "HOME"): True, (0, "AWAY"): True}
    assert rows.merge(store, rows.team_5min(team_agg(1, 321)), now_ms=4)[0]["window_index"] == 1  # 0-5' not resent
