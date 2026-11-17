"""theme.py: the colours of MatchLens that are not the page's own (.streamlit/config.toml sets the page: light by
default, dark as an option). These read well on both themes, so no page has to know which one is on:

  TEAM     Okabe-Ito blue and vermillion, the same in every match: told apart with the common colour blindnesses, at
           least 3:1 on both backgrounds; a team's name is always written next to its colour
  STATUS   fills for good / fixed or close / problem / nothing measured, with dark text on them (at least 4.8:1)
  ACCENT   green for lines and marks (not text): at least 3:1 on both backgrounds
Text uses the theme's own colour; quieter text is the same colour at 78 % opacity (MUTED_OPACITY).
"""
from pathlib import Path

TEAM = {"HOME": "#0072B2", "AWAY": "#D55E00"}
STATUS = {"green": "#2fbf71", "orange": "#f4a340", "red": "#e5484d", "grey": "#9aa5a0"}
ON_FILL = "#111111"
ACCENT = "#1f8f50"
GOLD = "#f4c430"
MUTED_OPACITY = 0.78
PITCH = "#123524"                # the turf of app/web3d/pitch.js, the same in both themes
OUTLINE = "#ffffff"              # around every player dot: 13.5:1 on the turf
BACKGROUNDS = {"light": ("#f7f6f1", "#eaede4", "#16201a"), "dark": ("#0b1410", "#12221a", "#e8f0ea")}
LOGO = str(Path(__file__).resolve().parent / "assets" / "matchlens-logo.svg")   # one file: sidebar and Home


def luminance(color: str) -> float:
    c = color.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio (1 to 21)."""
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def mix(fg: str, bg: str, alpha: float) -> str:
    """The colour seen when fg is drawn at `alpha` opacity over bg."""
    f, b = fg.lstrip("#"), bg.lstrip("#")
    return "#" + "".join(f"{round(int(f[i:i + 2], 16) * alpha + int(b[i:i + 2], 16) * (1 - alpha)):02x}"
                         for i in (0, 2, 4))
