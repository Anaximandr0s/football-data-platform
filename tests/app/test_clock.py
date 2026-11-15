"""The football clock (clock.py): the minute fans see on TV, checked on m001 against the official match report."""
import pytest

import clock

# m001 (SkillCorner 1874553) in Gold: the second half starts at ts 2899, which is match.json's kick-off frame 29000
M001 = (0, 2899)
M001_GOALS = [(326, 1, "6'"), (1934, 1, "33'"), (2538, 1, "43'"), (2936, 2, "46'"), (3890, 2, "62'")]


@pytest.mark.parametrize("ts, period, expected", M001_GOALS)
def test_m001_goals_read_like_the_match_report(ts, period, expected):
    # report: 6' Jelacic, 33' Mauk, 43' O'Shea, 46' Clough, 62' or 63' Goodwin (shot 16:31.8 into the second half)
    assert clock.label(ts, period, *M001) == expected


def test_stoppage_time_and_second_half():
    assert clock.label(2700, 1, *M001) == "45+1'"          # 45:00 into the first half
    assert clock.label(2890, 1, *M001) == "45+4'"          # the last second of m001's first half
    assert clock.label(2899, 2, *M001) == "46'"            # the second kick-off
    assert clock.label(2899 + 45 * 60, 2, *M001) == "90+1'"
    assert clock.label(3000, None, *M001) == "47'"         # period taken from the second kick-off when unknown


def test_running_clock_restarts_at_45():
    assert clock.running(1904, 1, *M001) == "31:44"
    assert clock.running(2780, 1, *M001) == "45:00 +1:20"
    assert clock.running(2899, 2, *M001) == "45:00"
    assert clock.running(2899 + 2700 + 5, 2, *M001) == "90:00 +0:05"


def test_windows_and_axis():
    assert clock.span(3600, 3900, *M001) == "57-62"
    assert clock.span(2700, 3000, *M001) == "45+1-47"     # the 5-minute window that holds half-time
    ticks = dict((label, value) for value, label in clock.axis_ticks(*M001, end_ts=6025))
    assert list(ticks) == ["0'", "15'", "30'", "45'", "60'", "75'", "90'"]
    assert ticks["45'"] == pytest.approx(2899 / 60)        # the axis restarts at 45' at the second kick-off


def test_football_windows_restart_at_each_kick_off():
    w5 = clock.windows(0, 2890, 2899, 6025, 300)                    # m001
    assert [w[2] for w in w5] == ["0-5", "5-10", "10-15", "15-20", "20-25", "25-30", "30-35", "35-40", "40-45", "45+",
                                  "45-50", "50-55", "55-60", "60-65", "65-70", "70-75", "75-80", "80-85", "85-90", "90+"]
    assert w5[9] == (9, 1, "45+", 2700, 2891)                         # 191 s of first-half stoppage time
    assert w5[10] == (10, 2, "45-50", 2899, 3199) and w5[19] == (19, 2, "90+", 5599, 6026)
    assert [w[2] for w in clock.windows(0, 2890, 2899, 6025, 900)] == ["0-15", "15-30", "30-45", "45+", "45-60", "60-75",
                                                                       "75-90", "90+"]
    assert clock.window_index(2936, 2, *M001) == 10 and clock.window_index(3890, 2, *M001) == 13   # Clough, Goodwin
    assert clock.window_index(2800, 1, *M001) == 9 and clock.window_index(2800, 1, *M001, size=900) == 3
