"""charts.with_crossings: the possession and territory areas must follow their line where it crosses 50 %."""

import pandas as pd

import charts


def test_a_point_is_added_where_the_line_crosses_the_level():
    points = pd.DataFrame({"minute": [0.0, 10.0, 20.0], "share": [0.4, 0.6, 0.7]})
    out = charts.with_crossings(points, "share")
    assert list(out.minute) == [0.0, 5.0, 10.0, 20.0] and out.share[1] == 0.5


def test_no_crossing_is_invented_across_a_missing_value():
    points = pd.DataFrame({"minute": [0.0, 10.0, 20.0], "share": [0.4, None, 0.7]})
    assert len(charts.with_crossings(points, "share")) == 3
