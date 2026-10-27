import pandas as pd
import pytest

from data_gen.common import EVENT_COLS, MAX_SPEED_KMH, PITCH_L, PITCH_W, TRACKING_COLS
from data_gen.sim import simulate_match

VALID_TYPES = {"pass", "shot", "goal", "tackle", "foul", "corner"}


@pytest.fixture(scope="module")
def match():
    return simulate_match("m001", seed=42)


def test_volumes(match):
    players, tracking, events = match
    assert len(players) == 22
    assert len(tracking) == 118_800
    assert len(events) >= 1000


def test_schemas(match):
    _, tracking, events = match
    assert list(tracking.columns) == TRACKING_COLS
    assert list(events.columns) == EVENT_COLS
    assert set(events["type"]) <= VALID_TYPES


def test_22_players_every_second(match):
    _, tracking, _ = match
    assert (tracking.groupby("ts").size() == 22).all()
    assert tracking["ts"].min() == 0 and tracking["ts"].max() == 5399


def test_inside_pitch_and_speed_cap(match):
    _, tracking, _ = match
    assert tracking["x"].between(0, PITCH_L).all()
    assert tracking["y"].between(0, PITCH_W).all()
    assert tracking["speed_kmh"].max() <= MAX_SPEED_KMH


def test_realistic_distance(match):
    _, tracking, _ = match
    km = tracking.groupby("player_id")["speed_kmh"].sum() / 3.6 / 1000
    assert 6 < km.mean() < 13


def test_no_teleport(match):
    _, tracking, _ = match
    t = tracking.sort_values(["player_id", "ts"])
    step = ((t.groupby("player_id")["x"].diff() ** 2 + t.groupby("player_id")["y"].diff() ** 2) ** 0.5)
    assert step.max() <= 12  # metres in one second


def test_reproducible():
    a = simulate_match("m001", seed=7)[1]
    b = simulate_match("m001", seed=7)[1]
    pd.testing.assert_frame_equal(a, b)
