"""Readable on a projector and for colour-blind visitors: every colour pair of theme.py and config.toml, in both themes."""

import tomllib
from pathlib import Path

import theme

CONFIG = tomllib.loads(
    (Path(__file__).resolve().parents[2] / "app" / "streamlit" / ".streamlit" / "config.toml").read_text(
        encoding="utf-8"
    )
)


def test_the_config_has_a_light_default_and_a_dark_option_with_the_colours_of_theme_py():
    assert CONFIG["theme"]["base"] == "light"
    for name, (bg, secondary, text) in theme.BACKGROUNDS.items():
        t = CONFIG["theme"][name]
        assert (t["backgroundColor"], t["secondaryBackgroundColor"], t["textColor"]) == (bg, secondary, text)
        assert t["chartCategoricalColors"][:2] == [theme.TEAM["HOME"], theme.TEAM["AWAY"]]


def test_text_is_at_least_4_5_to_1_everywhere():
    for bg, secondary, text in theme.BACKGROUNDS.values():
        for surface in (bg, secondary):
            assert theme.contrast(text, surface) >= 4.5
            assert theme.contrast(theme.mix(text, surface, theme.MUTED_OPACITY), surface) >= 4.5
    assert theme.contrast("#ffffff", CONFIG["theme"]["light"]["primaryColor"]) >= 4.5  # the buttons
    for fill in (*theme.STATUS.values(), theme.GOLD):
        assert theme.contrast(theme.ON_FILL, fill) >= 4.5


def test_team_colours_and_marks_are_at_least_3_to_1_on_both_themes_and_on_the_pitch_with_their_outline():
    for bg, secondary, _ in theme.BACKGROUNDS.values():
        for color in (*theme.TEAM.values(), theme.ACCENT):
            assert theme.contrast(color, bg) >= 3 and theme.contrast(color, secondary) >= 3
    assert theme.contrast(theme.OUTLINE, theme.PITCH) >= 3  # the dot is found by its outline on the turf
    assert theme.TEAM == {"HOME": "#0072B2", "AWAY": "#D55E00"}  # Okabe-Ito, in every match
