"""Colour rules and figures of app/streamlit/viz.py (no Gold, no dbt needed)."""
import sys
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("mplsoccer")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app" / "streamlit"))
import viz  # noqa: E402


def teams(home, away):
    return pd.DataFrame({"match_id": ["m", "m"], "team_id": ["HOME", "AWAY"], "team_color": [home, away]})


def test_usable_kit_colours_are_kept():
    assert viz.team_colors(teams("#e0a000", "#ffffff"), "m") == {"HOME": "#e0a000", "AWAY": "#ffffff"}


def test_a_dark_kit_colour_is_replaced_because_it_vanishes_on_the_dark_pitch():
    colors = viz.team_colors(teams("#363636", "#ffffff"), "m")          # m001 in the source
    assert colors == {"HOME": viz.DEFAULT_COLORS["HOME"], "AWAY": "#ffffff"}


def test_missing_invalid_or_similar_colours_fall_back_to_the_defaults():
    assert viz.team_colors(teams(None, "not a colour"), "m") == viz.DEFAULT_COLORS
    assert viz.team_colors(teams("#ff0000", "#f01010"), "m") == viz.DEFAULT_COLORS


def test_figures_are_built_for_a_minimal_input():
    zones = pd.DataFrame({"zone_x": [0, 5], "zone_y": [0, 3], "share_of_tracked_seconds": [0.4, 0.6]})
    assert viz.zone_heatmap(zones, "#e63946") is not None
    shots = pd.DataFrame({"team_id": ["HOME", "AWAY"], "is_goal": [True, False], "x_start": [95.0, 12.0],
                          "y_start": [34.0, 30.0], "x_end": [105.0, 0.0], "y_end": [34.0, 30.0]})
    assert viz.shot_map(shots, viz.DEFAULT_COLORS) is not None
