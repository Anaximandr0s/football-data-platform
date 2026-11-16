"""Live player stats (playerstats.py through live.apply) against Gold, and the Silver rules they repeat."""
import importlib.util
from pathlib import Path

import pytest

import live
import playerstats

duckdb = pytest.importorskip("duckdb")


def _load_gold_fixture():
    """The tiny Silver of tests/dbt (by path: a `conftest` import could resolve to another test folder's)."""
    spec = importlib.util.spec_from_file_location(
        "gold_fixture", Path(__file__).resolve().parents[1] / "dbt" / "test_gold_models.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_silver_frame_flips_where_home_attacks_left_and_clips():
    assert playerstats.silver_xy(10.0, 20.0, 1, "left_to_right", "right_to_left") == (10.0, 20.0)
    assert playerstats.silver_xy(10.0, 20.0, 2, "left_to_right", "right_to_left") == (95.0, 48.0)
    assert playerstats.silver_xy(-1.5, 70.0, 1, "left_to_right", "right_to_left") == (0.0, 68.0)


def test_zone_edges_match_gold():
    assert playerstats.zone_of(0.0, 0.0) == 0
    assert playerstats.zone_of(105.0, 68.0) == 23           # the far edges stay in the last cell
    assert playerstats.zone_of(50.0, 34.0) == 14


def test_sprint_efforts_top_speed_and_heat():
    s = playerstats.Second
    stats = playerstats.player_stats([s(1, 10, 10, 26.0, True), s(2, 10, 10, 27.0, True), s(4, 10, 10, 30.0, False),
                                      s(5, 10, 10, 20.0, True), s(0, 10, 10, None, True)])
    assert stats.sprint_count == 2                          # ts 1-2 is one effort; ts 4 follows a missing second
    assert stats.top_speed_kmh == 26.0                      # 26 then 27 held over ts 1-2; 30 at ts 4 is estimated
    assert stats.distance_m == pytest.approx((26 + 27 + 30 + 20) / 3.6)
    assert playerstats.heat_cells(stats.zones)[0] == 1.0


def _state_from(tracking, matches_row) -> live.MatchState:
    state = live.apply(live.MatchState("m1"), "matches", matches_row, 0)
    for i, r in enumerate(tracking.to_dict("records")):
        state = live.apply(state, "tracking", {**r, "speed_kmh": None if r["speed_kmh"] != r["speed_kmh"] else r["speed_kmh"]},
                           1 + i)
    return state


def test_live_stats_at_full_time_equal_gold(gold_env):
    fixture = _load_gold_fixture()
    tracking, matches_row = fixture._tracking(), fixture._matches().iloc[0].to_dict()
    state = _state_from(tracking, matches_row)
    state = live.apply(state, "tracking", tracking.iloc[1].to_dict(), 999)      # a message delivered twice
    con = duckdb.connect(gold_env["GOLD_DUCKDB_PATH"], read_only=True)
    gold = con.sql("select s.player_id, s.tracked_seconds, s.distance_m, s.sprint_count, c.top_speed_kmh "
                   "from gold_player_match_stats s join gold_player_card c using (match_id, player_id)").df()
    zones = con.sql("select player_id, zone_id, seconds from gold_zone_occupancy").df()
    for row in gold.itertuples():
        stats = live.player_stats(state, row.player_id)
        assert stats.tracked_seconds == row.tracked_seconds
        assert round(stats.distance_m, 1) == row.distance_m
        assert stats.sprint_count == row.sprint_count
        assert (stats.top_speed_kmh is None and row.top_speed_kmh != row.top_speed_kmh) or \
            round(stats.top_speed_kmh, 1) == row.top_speed_kmh
        assert stats.zones == {int(z.zone_id): int(z.seconds) for z in zones[zones.player_id == row.player_id].itertuples()}
    h01 = live.player_stats(state, "H01")
    assert (h01.sprint_count, h01.top_speed_kmh) == (4, 27.0)               # held over ts 9-10, as gold_player_card


def test_a_new_replay_starts_the_stats_again(gold_env):
    fixture = _load_gold_fixture()
    tracking, matches_row = fixture._tracking(), fixture._matches().iloc[0].to_dict()
    states = {"m1": _state_from(tracking, matches_row)}
    states = live.route(states, "m1-20261116T110000Z", "matches", matches_row, 10_000)   # a new replay of the match
    states = live.route(states, "m1-20261116T110000Z", "tracking",
                        {**tracking.iloc[1].to_dict(), "speed_kmh": 10.0}, 10_001)
    assert live.player_stats(states["m1"], "H01").tracked_seconds == 1
