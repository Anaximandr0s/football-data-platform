"""views.py: the shot map and the pass network on the pitch component, shared by Match story and Team analysis, and the
team key written above a chart."""
import html

import numpy as np
import pandas as pd

import pitch

MIN_PASSES = 3   # a pass-network line needs at least this many passes between two players


def team_key(colors: dict, names: dict) -> str:
    """HTML: a colour square and the team's name, for both teams (a colour is never shown without its name)."""
    return "".join(f"<span class='ml-key'><i style='background:{colors[t]}'></i>{html.escape(str(names[t]))}</span>"
                   for t in ("HOME", "AWAY"))


def shot_map(key: str, shots: pd.DataFrame, colors: dict) -> None:
    pitch.show(key=key, players={}, colors=colors, clickable=False, arrows={"home": "right"},
               shots=[[r.x_start, r.y_start, r.x_end, r.y_end, bool(r.is_goal), colors[r.team_id]]
                      for r in shots.itertuples()])


def pass_network(key: str, network: pd.DataFrame, stats: pd.DataFrame, card: pd.DataFrame, team: str,
                 colors: dict) -> None:
    """Players at their average position, a line per pair with at least MIN_PASSES passes, the hub ringed in gold."""
    net = network[(network.team_id == team) & (network.passes >= MIN_PASSES)]
    pos = stats[stats.team_id == team].set_index("player_id")
    hubs = set(card[(card.team_id == team) & card.is_hub].player_id)
    ids = sorted(set(net.passer_id) | set(net.receiver_id))
    pitch.show(key=key, players={}, colors=colors, clickable=False, arrows={"home": "right"},
               network={"color": colors[team],
                        "nodes": [[pos.loc[p, "avg_x"], pos.loc[p, "avg_y"], int(pos.loc[p, "passes"]),
                                   int(pos.loc[p, "shirt_number"]), p in hubs] for p in ids if p in pos.index],
                        "edges": [[pos.loc[r.passer_id, "avg_x"], pos.loc[r.passer_id, "avg_y"],
                                   pos.loc[r.receiver_id, "avg_x"], pos.loc[r.receiver_id, "avg_y"], int(r.passes)]
                                  for r in net.itertuples() if r.passer_id in pos.index and r.receiver_id in pos.index]})


def directions(ev: pd.DataFrame, grid: tuple[int, int]) -> list[list]:
    """The average move of the events starting in each heatmap cell, drawn from the cell's centre: [x, y, xe, ye, ok]
    (ok = most of them successful). Cells with fewer than 3 events are left out."""
    nx, ny = grid
    d = ev.dropna(subset=["x_end", "y_end"]).assign(
        zx=lambda e: np.minimum((e.x_start / 105 * nx).astype(int), nx - 1),
        zy=lambda e: np.minimum((e.y_start / 68 * ny).astype(int), ny - 1),
        dx=lambda e: e.x_end - e.x_start, dy=lambda e: e.y_end - e.y_start,
        ok=lambda e: (e.outcome == "successful") | e.received.fillna(False).astype(bool))
    out = []
    for (zx, zy), g in d.groupby(["zx", "zy"]):
        if len(g) >= 3:
            cx, cy = (zx + 0.5) * 105 / nx, (zy + 0.5) * 68 / ny
            out.append([cx, cy, cx + g.dx.mean(), cy + g.dy.mean(), bool(g.ok.mean() >= 0.5)])
    return out
