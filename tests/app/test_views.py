"""Pitch helpers of app/streamlit/views.py that hold logic: the average direction per zone (Event explorer)."""

import pandas as pd

import views


def test_directions_average_the_moves_of_each_zone_with_at_least_three_events():
    ev = pd.DataFrame(
        {
            "x_start": [1, 2, 3, 90, 91],
            "y_start": [1, 2, 3, 60, 61],
            "x_end": [11, 12, 13, 95, 96],
            "y_end": [1, 2, 3, 60, 61],
            "outcome": ["successful", "successful", "unsuccessful", "successful", "successful"],
            "received": [None] * 5,
        }
    )
    arrows = views.directions(ev, (12, 8))
    assert len(arrows) == 1  # the 2 events near x = 90 are too few
    x, y, xe, ye, ok = arrows[0]
    assert (round(x, 3), round(y, 3)) == (round(105 / 24, 3), round(68 / 16, 3))  # the centre of cell (0, 0)
    assert (round(xe - x, 6), ye - y, ok) == (10.0, 0.0, True)  # 10 m forward on average, 2 of 3 successful
