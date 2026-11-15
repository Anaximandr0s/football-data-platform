"""pitch.py: the MatchLens pitch (docs/product.md, section 8.2), one canvas component for Live, Replay and the Player
page. The drawing is app/web3d/pitch.js; this module only shapes the data and returns the player a visitor clicked.

Coordinates are metres on a 105 x 68 pitch, origin bottom-left (the frame of the data passed in: Gold for the Player
page, the camera for Live).
"""
from pathlib import Path

import streamlit as st

_JS = (Path(__file__).resolve().parents[1] / "web3d" / "pitch.js").read_text(encoding="utf-8")
_component = st.components.v2.component("matchlens_pitch", js=_JS)


def frame_list(ts: int, ball: tuple | None, positions: dict) -> list:
    """One second as the component reads it: [ts, ball x, ball y, id, x, y, detected, ...]."""
    out = [ts, *(ball if ball else (None, None))]
    for pid, (x, y, detected) in positions.items():
        out += [pid, round(x, 2), round(y, 2), bool(detected)]
    return out


def show(*, key: str, players: dict, colors: dict, frame: list | None = None, frames: dict | None = None,
         start: int | None = None, speed: float = 1.0, heat: dict | None = None, shots: list | None = None,
         passes: list | None = None, selected: str | None = None, arrows: dict | None = None,
         message: str | None = None, clickable: bool = True) -> str | None:
    """Draw the pitch; return the id of the player clicked in this run (None if no click)."""
    data = {"players": players, "colors": colors, "frame": frame, "frames": frames, "start": start, "speed": speed,
            "heat": heat, "shots": shots, "passes": passes, "selected": selected, "arrows": arrows,
            "message": message, "clickable": clickable}
    result = _component(data=data, key=key, on_player_change=lambda: None)
    return result.player
