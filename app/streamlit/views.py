"""views.py: the shot map and the pass network on the pitch component, shared by Match story and Team analysis."""
import pandas as pd

import pitch

MIN_PASSES = 3   # a pass-network line needs at least this many passes between two players


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
