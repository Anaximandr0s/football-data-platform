"""rows.py: the rows of foot-live-stats, built from the window counts of the streaming job. Pure Python: no
Spark, no Kafka, so the formulas and the completion rule are unit-tested (tests/spark/test_streaming_rows.py).

Each row is the full current value of one window (never an increment): sending it again after a restart overwrites,
and the compacted topic keeps the latest row per key. The formulas and names are those of Gold:
  team, 5 min    gold_match_timeline: possession seconds and share (greyed under 60 known seconds), passes, defensive
                 actions (pressure + tackle + foul), plus pressing per opponent pass (greyed under 10 passes)
  player, 5 min  gold_player_5min: tracked seconds, coverage, distance, sprint seconds, top speed
  team, 15 min   gold_pressing: defensive actions, opponent passes, ppp, actions per third, high_press_share
A window is complete once the replay's tracking has passed its end + GRACE_S seconds of match time (messages of other
topics may arrive a little late), or has reached the last second of the match.
"""
import clock

GRACE_S = 10
POSSESSION_MIN_KNOWN_S = 60    # as gold_match_timeline.possession_greyed
PPP_MIN_PASSES = 10            # as gold_pressing.ppp_greyed


def bounds(window_index: int, size: int, p1_start: int, p1_end: int, p2_start: int, p2_end: int) -> tuple:
    """(label, start_ts, end_ts exclusive) of a football window."""
    for index, _period, label, start, end in clock.windows(p1_start, p1_end, p2_start, p2_end, size):
        if index == window_index:
            return label, start, end
    raise ValueError(f"no window {window_index} of {size} s in this match")


def _ratio(a: float, b: float, digits: int = 4) -> float | None:
    return round(a / b, digits) if b else None


def _window(agg: dict, size: int) -> dict:
    label, start, end = bounds(agg["window_index"], size, agg["p1_start_ts"], agg["p1_end_ts"], agg["p2_start_ts"],
                               agg["p2_end_ts"])
    return {"replay_id": agg["replay_id"], "match_id": agg["match_id"], "window_size": size,
            "window_index": agg["window_index"], "window_label": label, "window_start_ts": start,
            "window_end_ts": end, "window_seconds": end - start, "last_ts": agg["last_ts"],
            "p2_end_ts": agg["p2_end_ts"]}


def team_5min(agg: dict) -> list[dict]:
    """agg: home_/away_ possession seconds, passes and defensive actions of one 5-minute window."""
    w = _window(agg, 300)
    known = agg["home_possession"] + agg["away_possession"]
    out = []
    for team, opp in (("home", "away"), ("away", "home")):
        passes_opp = agg[f"{opp}_passes"]
        out.append({**w, "kind": "team", "team_id": team.upper(),
                    "possession_seconds": agg[f"{team}_possession"], "known_seconds": known,
                    "possession_share": _ratio(agg[f"{team}_possession"], known),
                    "possession_greyed": known < POSSESSION_MIN_KNOWN_S,
                    "passes": agg[f"{team}_passes"], "defensive_actions": agg[f"{team}_da"],
                    "opponent_passes": passes_opp, "ppp": _ratio(agg[f"{team}_da"], passes_opp),
                    "ppp_greyed": passes_opp < PPP_MIN_PASSES})
    return out


def team_15min(agg: dict) -> list[dict]:
    """agg: home_/away_ passes, defensive actions and defensive actions per third of one 15-minute window."""
    w = _window(agg, 900)
    out = []
    for team, opp in (("home", "away"), ("away", "home")):
        da, passes_opp = agg[f"{team}_da"], agg[f"{opp}_passes"]
        out.append({**w, "kind": "pressing", "team_id": team.upper(), "defensive_actions": da,
                    "opponent_passes": passes_opp, "ppp": _ratio(da, passes_opp),
                    "ppp_greyed": passes_opp < PPP_MIN_PASSES,
                    "defensive_actions_own_third": agg[f"{team}_da_own"],
                    "defensive_actions_middle_third": agg[f"{team}_da_middle"],
                    "defensive_actions_final_third": agg[f"{team}_da_final"],
                    "high_press_share": _ratio(agg[f"{team}_da_final"], da)})
    return out


def player_5min(agg: dict) -> dict:
    """agg: tracked seconds, distance, sprint seconds and top speed of one player in one 5-minute window."""
    w = _window(agg, 300)
    return {**w, "kind": "player", "team_id": agg["team_id"], "player_id": agg["player_id"],
            "tracked_seconds": agg["tracked_seconds"], "coverage": round(agg["tracked_seconds"] / w["window_seconds"], 3),
            "distance_m": round(agg["distance_m"] or 0.0, 1), "sprint_seconds": agg["sprint_seconds"],
            "max_speed_kmh": None if agg["max_speed_kmh"] is None else round(agg["max_speed_kmh"], 2)}


def key(row: dict) -> str:
    """replay_id|match_id|window size|window index|team or player."""
    who = row.get("player_id") or row["team_id"]
    return f"{row['replay_id']}|{row['match_id']}|{row['window_size']}|{row['window_index']}|{who}"


def is_complete(row: dict, progress: int) -> bool:
    """progress: the latest tracked second of the replay."""
    return progress >= row["window_end_ts"] + GRACE_S or progress >= row["p2_end_ts"]   # window_end_ts: exclusive


def merge(store: dict[str, dict], updated: list[dict], now_ms: int) -> list[dict]:
    """Put the updated rows in `store` (key -> latest row sent) and return every row to send: the updated ones, and the
    stored rows of the same replays that became complete. Progress of a replay = the latest last_ts of its rows."""
    progress: dict[str, int] = {}
    for row in [*store.values(), *updated]:
        progress[row["replay_id"]] = max(progress.get(row["replay_id"], -1), row["last_ts"])
    out = {}
    for row in updated:
        out[key(row)] = {**row, "complete": is_complete(row, progress[row["replay_id"]]), "updated_at": now_ms}
    touched = {row["replay_id"] for row in updated}
    for k, row in store.items():
        if k not in out and row["replay_id"] in touched and not row["complete"] \
                and is_complete(row, progress[row["replay_id"]]):
            out[k] = {**row, "complete": True, "updated_at": now_ms}
    store.update(out)
    return list(out.values())
