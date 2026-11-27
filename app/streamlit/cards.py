"""cards.py: the shirt and the badges of the player cards (Squad, Player page). HTML strings, no Streamlit."""

import html


def _luminance(color: str) -> float:
    r, g, b = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def shirt(color: str, number, size: int = 64) -> str:
    """A football shirt in the team colour with the shirt number; dark number on a light shirt."""
    ink = "#0b1410" if _luminance(color) > 0.6 else "#ffffff"
    return (
        f"<svg width='{size}' height='{size}' viewBox='0 0 64 64' role='img' aria-label='shirt {number}'>"
        f"<path d='M22 6 L32 11 L42 6 L58 16 L52 28 L46 25 L46 58 L18 58 L18 25 L12 28 L6 16 Z' "
        f"fill='{color}' stroke='rgba(232,240,234,.55)' stroke-width='1.5' stroke-linejoin='round'/>"
        f"<text x='32' y='45' text-anchor='middle' font-family='system-ui,sans-serif' font-weight='800' "
        f"font-size='20' fill='{ink}'>{html.escape(str(number))}</text></svg>"
    )


def badge(text: str, kind: str = "info") -> str:
    """kind: gold (a distinction), info (a fact), muted (a limit, e.g. not ranked)."""
    return f"<span class='ml-chip ml-chip-{kind}'>{html.escape(text)}</span>"
