"""viz.py: the football graphics (mplsoccer on a 105 x 68 m pitch). Pure functions: DataFrames in, figure out.

Frame of every Gold table: origin bottom-left, HOME attacks toward x = 105 and AWAY toward x = 0, in both halves.
"""
import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from mplsoccer import Pitch  # noqa: E402

PITCH_L, PITCH_W = 105.0, 68.0
ZONES_X, ZONES_Y = 6, 4
DEFAULT_COLORS = {"HOME": "#e63946", "AWAY": "#1d8fe1"}
BG = "#0e1117"
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def team_colors(teams: pd.DataFrame, match_id: str) -> dict[str, str]:
    """Kit colours of the match. The source sometimes gives none or two similar ones: fall back to fixed colours."""
    rows = teams[teams.match_id == match_id].set_index("team_id")
    colors = dict(DEFAULT_COLORS)
    for side in ("HOME", "AWAY"):
        value = rows["team_color"].get(side) if "team_color" in rows else None
        # a kit colour that is too dark disappears on the dark pitch (m001 HOME is #363636): keep the default then
        if isinstance(value, str) and _HEX.match(value) and _luminance(value) >= 0.25:
            colors[side] = value
    if _distance(colors["HOME"], colors["AWAY"]) < 90:
        colors = dict(DEFAULT_COLORS)
    return colors


def _luminance(color: str) -> float:
    """Relative brightness 0 (black) to 1 (white)."""
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _distance(a: str, b: str) -> float:
    ra, rb = (np.array([int(c[i:i + 2], 16) for i in (1, 3, 5)]) for c in (a, b))
    return float(np.linalg.norm(ra - rb))


def draw_pitch(figsize=(9, 6)):
    pitch = Pitch(pitch_type="custom", pitch_length=PITCH_L, pitch_width=PITCH_W, pitch_color="#1c2b24",
                  line_color="#c9d3cd", linewidth=1.2, goal_type="box")
    fig, ax = pitch.draw(figsize=figsize)
    fig.patch.set_facecolor(BG)
    return pitch, fig, ax


def _attack_arrows(ax, home_color: str, away_color: str) -> None:
    ax.annotate("", xy=(70, -2.6), xytext=(35, -2.6), annotation_clip=False,
                arrowprops={"arrowstyle": "->", "color": home_color, "lw": 2})
    ax.annotate("", xy=(35, 70.6), xytext=(70, 70.6), annotation_clip=False,
                arrowprops={"arrowstyle": "->", "color": away_color, "lw": 2})


def zone_heatmap(zones: pd.DataFrame, color: str) -> plt.Figure:
    """Share of the tracked seconds spent in each cell of the 6 x 4 grid (cells never visited show 0 %)."""
    grid = np.zeros((ZONES_Y, ZONES_X))
    for r in zones.itertuples():
        grid[int(r.zone_y), int(r.zone_x)] = r.share_of_tracked_seconds
    _, fig, ax = draw_pitch((8, 5.4))
    peak = grid.max() or 1.0
    cell_w, cell_h = PITCH_L / ZONES_X, PITCH_W / ZONES_Y
    for zy in range(ZONES_Y):
        for zx in range(ZONES_X):
            share = grid[zy, zx]
            ax.add_patch(Rectangle((zx * cell_w, zy * cell_h), cell_w, cell_h, facecolor=color,
                                   alpha=0.08 + 0.80 * share / peak, edgecolor="none", zorder=1))
            ax.text((zx + 0.5) * cell_w, (zy + 0.5) * cell_h, f"{share:.0%}", ha="center", va="center",
                    color="white", fontsize=10, zorder=3, alpha=0.95 if share else 0.35)
    return fig


def shot_map(shots: pd.DataFrame, colors: dict[str, str]) -> plt.Figure:
    """Both teams on one pitch: HOME shoots toward the right goal, AWAY toward the left goal."""
    pitch, fig, ax = draw_pitch()
    for team, group in shots.groupby("team_id"):
        color = colors[team]
        misses, goals = group[~group.is_goal], group[group.is_goal]
        pitch.lines(group.x_start, group.y_start, group.x_end, group.y_end, ax=ax, color=color, alpha=0.25, lw=1,
                    zorder=2)
        pitch.scatter(misses.x_start, misses.y_start, ax=ax, s=110, facecolor="none", edgecolor=color, lw=2, zorder=4)
        pitch.scatter(goals.x_start, goals.y_start, ax=ax, s=420, marker="*", facecolor=color, edgecolor="white",
                      lw=1, zorder=5)
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
            pitch.lines(a.avg_x, a.avg_y, b.avg_x, b.avg_y, ax=ax, color=color, alpha=0.55,
                        lw=0.6 + e.passes * 0.45, zorder=2)
    made = network.groupby("passer_id").passes.sum()
    light = _luminance(color) > 0.6                      # dark number on a light node, light number on a dark one
    label, rim = ("#0e1117", "#8a948f") if light else ("white", "white")
    for pid, p in nodes.iterrows():
        size = 160 + 14 * made.get(pid, 0)
        pitch.scatter(p.avg_x, p.avg_y, ax=ax, s=size, facecolor=color, edgecolor=rim, lw=1.4, zorder=4)
        ax.text(p.avg_x, p.avg_y, str(int(p.shirt_number)), ha="center", va="center", color=label,
                fontsize=9, fontweight="bold", zorder=5)
    return fig


def live_pitch(positions: dict, players: dict, ball: tuple | None, colors: dict[str, str],
               home_attacks_right: bool | None, message: str | None = None) -> plt.Figure:
    """One second of the replay as the camera shows it (teams switch ends at half-time). `positions`:
    {player_id: (x, y, is_detected)}; `ball`: (x, y) or None; `message` replaces the dots (camera gap)."""
    pitch, fig, ax = draw_pitch((9, 6))
    if message:
        ax.text(PITCH_L / 2, PITCH_W / 2, message, ha="center", va="center", color="white", fontsize=15,
                bbox={"facecolor": BG, "alpha": 0.85, "edgecolor": "#c9d3cd", "boxstyle": "round,pad=0.6"}, zorder=6)
        return fig
    for pid, (x, y, detected) in positions.items():
        p = players.get(pid, {})
        color = colors.get(p.get("team_id"), "#8a948f")
        label = "#0e1117" if _luminance(color) > 0.6 else "white"
        # an estimated position (camera did not see the player) is drawn lighter
        pitch.scatter(x, y, ax=ax, s=330, facecolor=color, edgecolor="white", lw=1.2,
                      alpha=1.0 if detected is not False else 0.45, zorder=4)
        ax.text(x, y, str(p.get("shirt_number", "")), ha="center", va="center", color=label, fontsize=8,
                fontweight="bold", zorder=5)
    if ball is not None:
        pitch.scatter(ball[0], ball[1], ax=ax, s=90, facecolor="white", edgecolor="#0e1117", lw=1.5, zorder=6)
    if home_attacks_right is not None:
        left, right = (colors["HOME"], colors["AWAY"]) if home_attacks_right else (colors["AWAY"], colors["HOME"])
        _attack_arrows(ax, left, right)
    return fig


def ranking_bars(df: pd.DataFrame, metric: str, colors: dict[str, str], top: int = 10) -> plt.Figure:
    best = df.nlargest(top, metric).iloc[::-1]
    fig, ax = plt.subplots(figsize=(7, 0.42 * len(best) + 1.2))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.barh(best.short_name, best[metric], color=[colors[t] for t in best.team_id])
    ax.tick_params(colors="#c9d3cd")
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.xaxis.label.set_color("#c9d3cd")
    ax.set_xlabel(metric)
    for y, v in enumerate(best[metric]):
        ax.text(v, y, f" {v:g}", va="center", color="#c9d3cd", fontsize=9)
    fig.tight_layout()
    return fig
