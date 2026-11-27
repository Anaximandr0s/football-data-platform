"""viz.py: the football graphics (mplsoccer on a 105 x 68 m pitch). Pure functions: DataFrames in, figure out.

Frame of every Gold table: origin bottom-left, HOME attacks toward x = 105 and AWAY toward x = 0, in both halves.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from mplsoccer import Pitch  # noqa: E402

import theme  # noqa: E402

PITCH_L, PITCH_W = 105.0, 68.0
DEFAULT_COLORS = dict(theme.TEAM)
BG = "#0b1410"  # the app background (.streamlit/config.toml)


def team_colors(teams: pd.DataFrame, match_id: str) -> dict[str, str]:  # noqa: ARG001 - one palette for all
    """The team colours of every match: Okabe-Ito blue (HOME) and vermillion (AWAY), readable by colour-blind
    visitors and on both themes. Kit colours are not used: a white kit vanishes on a light page."""
    return dict(theme.TEAM)


def possession_bar(home_share: float, colors: dict[str, str], names: dict[str, str]) -> str:
    """HTML of the possession bar of Live and Replay: the two team names and shares above a bar in their colours."""
    away_share = 1 - home_share
    return (
        f"<div style='display:flex;justify-content:space-between;font-size:.85rem;margin-bottom:3px'>"
        f"<span><b style='color:{colors['HOME']}'>&#9632;</b> {names['HOME']} {home_share:.0%}</span>"
        f"<span>{away_share:.0%} {names['AWAY']} <b style='color:{colors['AWAY']}'>&#9632;</b></span></div>"
        f"<div style='display:flex;height:16px;border-radius:4px;overflow:hidden'>"
        f"<div style='width:{home_share:.0%};background:{colors['HOME']}'></div>"
        f"<div style='width:{away_share:.0%};background:{colors['AWAY']}'></div></div>"
    )


def _luminance(color: str) -> float:
    """Relative brightness 0 (black) to 1 (white)."""
    r, g, b = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def draw_pitch(figsize=(9, 6)):
    pitch = Pitch(
        pitch_type="custom",
        pitch_length=PITCH_L,
        pitch_width=PITCH_W,
        pitch_color="#1c2b24",
        line_color="#c9d3cd",
        linewidth=1.2,
        goal_type="box",
    )
    fig, ax = pitch.draw(figsize=figsize)
    fig.patch.set_facecolor(BG)
    return pitch, fig, ax


def _attack_arrows(ax, home_color: str, away_color: str) -> None:
    ax.annotate(
        "",
        xy=(70, -2.6),
        xytext=(35, -2.6),
        annotation_clip=False,
        arrowprops={"arrowstyle": "->", "color": home_color, "lw": 2},
    )
    ax.annotate(
        "",
        xy=(35, 70.6),
        xytext=(70, 70.6),
        annotation_clip=False,
        arrowprops={"arrowstyle": "->", "color": away_color, "lw": 2},
    )


def shot_map(shots: pd.DataFrame, colors: dict[str, str]) -> plt.Figure:
    """Both teams on one pitch: HOME shoots toward the right goal, AWAY toward the left goal."""
    pitch, fig, ax = draw_pitch()
    for team, group in shots.groupby("team_id"):
        color = colors[team]
        misses, goals = group[~group.is_goal], group[group.is_goal]
        pitch.lines(
            group.x_start, group.y_start, group.x_end, group.y_end, ax=ax, color=color, alpha=0.25, lw=1, zorder=2
        )
        pitch.scatter(misses.x_start, misses.y_start, ax=ax, s=110, facecolor="none", edgecolor=color, lw=2, zorder=4)
        pitch.scatter(
            goals.x_start, goals.y_start, ax=ax, s=420, marker="*", facecolor=color, edgecolor="white", lw=1, zorder=5
        )
    _attack_arrows(ax, colors["HOME"], colors["AWAY"])
    return fig


def pass_network(network: pd.DataFrame, players: pd.DataFrame, color: str, min_passes: int) -> plt.Figure:
    """Nodes at the average position of each player (size = passes made), edges = passes between two players."""
    pitch, fig, ax = draw_pitch()
    edges = network[network.passes >= min_passes]
    nodes = players[players.player_id.isin(set(network.passer_id) | set(network.receiver_id))].set_index("player_id")
    for e in edges.itertuples():
        if e.passer_id in nodes.index and e.receiver_id in nodes.index:
            a, b = nodes.loc[e.passer_id], nodes.loc[e.receiver_id]
            pitch.lines(
                a.avg_x, a.avg_y, b.avg_x, b.avg_y, ax=ax, color=color, alpha=0.55, lw=0.6 + e.passes * 0.45, zorder=2
            )
    made = network.groupby("passer_id").passes.sum()
    light = _luminance(color) > 0.6  # dark number on a light node, light number on a dark one
    label, rim = ("#0e1117", "#8a948f") if light else ("white", "white")
    for pid, p in nodes.iterrows():
        size = 160 + 14 * made.get(pid, 0)
        pitch.scatter(p.avg_x, p.avg_y, ax=ax, s=size, facecolor=color, edgecolor=rim, lw=1.4, zorder=4)
        ax.text(
            p.avg_x,
            p.avg_y,
            str(int(p.shirt_number)),
            ha="center",
            va="center",
            color=label,
            fontsize=9,
            fontweight="bold",
            zorder=5,
        )
    return fig
