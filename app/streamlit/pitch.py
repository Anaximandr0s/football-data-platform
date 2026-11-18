"""pitch.py: the MatchLens pitch (docs/product.md, section 8.2), one canvas component for Live, Replay and the Player
page. The drawing is app/pitch/pitch.js; this module only shapes the data and returns the player a visitor clicked.

Coordinates are metres on a 105 x 68 pitch, origin bottom-left, in the Silver frame (HOME attacks toward x = 105) on
every page.
"""

from pathlib import Path

import streamlit as st

_WEB = Path(__file__).resolve().parents[1] / "pitch"
# d3-delaunay (Voronoi cells of the Replay) is a vendored UMD file that sets globalThis.d3 before pitch.js runs
_JS = (_WEB / "d3-delaunay.min.js").read_text(encoding="utf-8") + "\n" + (_WEB / "pitch.js").read_text(encoding="utf-8")
_component = st.components.v2.component("matchlens_pitch", js=_JS)


def frame_list(ts: int, ball: tuple | None, positions: dict) -> list:
    """One second as the component reads it: [ts, ball x, ball y, id, x, y, detected, ...]."""
    out = [ts, *(ball if ball else (None, None))]
    for pid, (x, y, detected) in positions.items():
        out += [pid, round(x, 2), round(y, 2), bool(detected)]
    return out


def show(
    *,
    key: str,
    players: dict,
    colors: dict,
    frame: list | None = None,
    heat: dict | None = None,
    shots: list | None = None,
    passes: list | None = None,
    network: dict | None = None,
    selected: str | None = None,
    arrows: dict | None = None,
    message: str | None = None,
    clickable: bool = True,
) -> str | None:
    """Draw the pitch; return the id of the player clicked in this run (None if no click)."""
    data = {
        "players": players,
        "colors": colors,
        "frame": frame,
        "heat": heat,
        "shots": shots,
        "passes": passes,
        "network": network,
        "selected": selected,
        "arrows": arrows,
        "message": message,
        "clickable": clickable,
    }
    result = _component(data=data, key=key, on_player_change=lambda: None)
    return result.player


def replay(
    *, key: str, players: dict, colors: dict, frames: dict, replay: dict, names: dict, selected: str | None = None
):
    """A whole match played in the browser (pitch.js, Replay). `frames` is the full match the first time and {key}
    afterwards. Returns the component result: .pick ({player, n}: the n-th click), .time (replay second), .reload
    (frames key to resend)."""
    data = {
        "players": players,
        "colors": colors,
        "frames": frames,
        "replay": replay,
        "selected": selected,
        "arrows": {"home": "right", "names": names},
        "clickable": True,
    }
    return _component(
        data=data, key=key, on_pick_change=lambda: None, on_time_change=lambda: None, on_reload_change=lambda: None
    )
