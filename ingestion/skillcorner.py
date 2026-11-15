"""skillcorner.py: everything that knows the SkillCorner open-data format.

These functions turn the raw files of one match into our tables (docs/contrat_donnees.md).
ingest_foot.py reads the files and writes the results; this module only transforms.
Nothing here cleans the data: no clipping, smoothing, direction flip or deduplication.
"""
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from ingestion.config import FPS, PITCH_L, PITCH_W

POSSESSION = {"home team": "HOME", "away team": "AWAY"}   # tracking `possession.group` -> our team keys


def first_frame(info: dict) -> int:
    return min(p["start_frame"] for p in info["match_periods"])


def playing_span(p: dict):
    """(start_frame, end_frame) while the player is on the pitch, None if he never played."""
    total = (p.get("playing_time") or {}).get("total")
    if total and total.get("start_frame") is not None:
        return total["start_frame"], total["end_frame"]
    return None


def full_name(p: dict) -> str:
    """'first last' without the stray spaces the source leaves around names."""
    return " ".join(f"{p.get('first_name') or ''} {p.get('last_name') or ''}".split())


def build_players(info: dict, match_id: str):
    """Players who were on the pitch, with ids H01.. / A01.. (match-local technical keys)."""
    first = first_frame(info)
    home_id = info["home_team"]["id"]
    rows, idmap, spans = [], {}, {}
    for side, prefix in (("HOME", "H"), ("AWAY", "A")):
        team = [p for p in info["players"]
                if (p["team_id"] == home_id) == (side == "HOME") and playing_span(p)]
        team.sort(key=lambda p: (playing_span(p)[0], p["number"]))
        for i, p in enumerate(team, start=1):
            pid = f"{prefix}{i:02d}"
            start, end = playing_span(p)
            idmap[p["id"]] = (pid, side)
            spans[p["id"]] = (start, end)
            rows.append((match_id, pid, side, full_name(p), p.get("short_name") or full_name(p),
                         p["player_role"]["acronym"], p["number"],
                         (start - first) // FPS, (end - first) // FPS, p["id"]))
    cols = ["match_id", "player_id", "team_id", "name", "short_name", "position",
            "shirt_number", "start_ts", "end_ts", "source_player_id"]
    return pd.DataFrame(rows, columns=cols), idmap, spans


def parse_tracking(lines, info: dict, idmap: dict, spans: dict, match_id: str):
    """Returns (tracking, ball, drops). Keeps 1 frame out of FPS, players on the pitch only."""
    first = first_frame(info)
    rows, ball_rows, drops = [], [], Counter()
    for line in lines:
        fr = json.loads(line)
        f, period = fr.get("frame"), fr.get("period")
        # frames before kick-off have no period and no players: nothing to keep
        if f is None or period is None or f < first or (f - first) % FPS:
            continue
        ts = (f - first) // FPS
        b = fr.get("ball_data") or {}
        if b.get("x") is None or b.get("y") is None:
            drops["ball_without_position"] += 1
        else:
            group = (fr.get("possession") or {}).get("group")
            ball_rows.append((match_id, ts, int(period), b["x"] + PITCH_L / 2,
                              b["y"] + PITCH_W / 2, b.get("z"), POSSESSION.get(group)))
        for p in fr.get("player_data") or []:
            sid = p.get("player_id")
            if sid not in idmap:
                drops["player_not_in_lineup"] += 1
                continue
            if p.get("x") is None or p.get("y") is None:
                drops["player_without_position"] += 1
                continue
            start, end = spans[sid]
            if not start <= f <= end:
                drops["player_outside_playing_time"] += 1
                continue
            rows.append((match_id, idmap[sid][0], ts, int(period),
                         p["x"] + PITCH_L / 2, p["y"] + PITCH_W / 2, p.get("is_detected")))

    tracking = pd.DataFrame(rows, columns=["match_id", "player_id", "ts", "period", "x", "y", "is_detected"])
    tracking = tracking.sort_values(["player_id", "ts"]).reset_index(drop=True)
    g = tracking.groupby("player_id")
    step = np.hypot(g["x"].diff(), g["y"].diff())
    # speed = distance covered since the previous second; null when there is no previous second
    tracking["speed_kmh"] = np.where(g["ts"].diff() == 1, step * 3.6, np.nan)
    tracking[["x", "y", "speed_kmh"]] = tracking[["x", "y", "speed_kmh"]].round(2)
    tracking = tracking.sort_values(["ts", "player_id"]).reset_index(drop=True)

    ball = pd.DataFrame(ball_rows, columns=["match_id", "ts", "period", "x", "y", "z", "possession"]).round(2)
    return tracking, ball, drops


def _goal_shot_index(d: pd.DataFrame, home_id: int) -> set:
    """SkillCorner has no goal flag: a goal = the last shot of a team before its score increases."""
    d = d[["frame_start", "team_id", "team_score", "opponent_team_score",
           "event_type", "end_type"]].sort_values("frame_start").copy()
    is_home = d["team_id"] == home_id
    d = d.assign(home_score=np.where(is_home, d["team_score"], d["opponent_team_score"]),
                 away_score=np.where(is_home, d["opponent_team_score"], d["team_score"]))
    goals = set()
    shots = d[(d["event_type"] == "player_possession") & (d["end_type"] == "shot")]
    for side, col in (("home", "home_score"), ("away", "away_score")):
        inc = d.loc[d[col].diff() > 0, "frame_start"]
        for f in inc:
            cand = shots[(shots["frame_start"] <= f) & ((shots["team_id"] == home_id) == (side == "home"))]
            if len(cand):
                goals.add(cand.index[-1])
    return goals


def parse_events(csv_path: Path, info: dict, idmap: dict, match_id: str) -> pd.DataFrame:
    raw = pd.read_csv(csv_path, low_memory=False)
    first = first_frame(info)
    home_id = info["home_team"]["id"]
    goal_idx = _goal_shot_index(raw, home_id)
    d = raw[raw["player_id"].isin(list(idmap))].copy()
    pp = d["event_type"] == "player_possession"
    eng = d["event_type"] == "on_ball_engagement"
    kind = pd.Series(np.nan, index=d.index, dtype=object)
    kind.loc[pp & (d["end_type"] == "pass")] = "pass"
    kind.loc[pp & (d["end_type"] == "shot")] = "shot"
    kind.loc[d.index.isin(goal_idx)] = "goal"
    kind.loc[eng] = "pressure"
    kind.loc[eng & d["end_type"].isin(["direct_regain", "direct_disruption"])] = "tackle"
    kind.loc[eng & (d["end_type"] == "foul_committed")] = "foul"
    kind.loc[d["event_type"] == "off_ball_run"] = "run"
    d["type"] = kind
    d = d[d["type"].notna()]

    # pass destination = where the targeted player received the ball, else the possession end point
    is_pass = d["type"].eq("pass")
    is_run = d["type"].eq("run")
    is_engagement = d["event_type"].eq("on_ball_engagement")
    x_end = np.where(is_pass & d["player_targeted_x_reception"].notna(),
                     d["player_targeted_x_reception"], d["x_end"])
    y_end = np.where(is_pass & d["player_targeted_y_reception"].notna(),
                     d["player_targeted_y_reception"], d["y_end"])
    # receiver of a pass = the targeted player (null for other types, or if he is not in the lineup)
    receiver = d["player_targeted_id"].map(
        lambda i: idmap[int(i)][0] if pd.notna(i) and int(i) in idmap else None)
    out = pd.DataFrame({
        "match_id": match_id,
        "ts": ((d["frame_start"] - first) // FPS).clip(lower=0).astype(int),
        "period": d["period"].fillna(0).astype(int),
        "player_id": d["player_id"].map(lambda i: idmap[i][0]),
        "receiver_id": receiver.where(is_pass),
        "team_id": np.where(d["team_id"] == home_id, "HOME", "AWAY"),
        "type": d["type"],
        "x_start": (d["x_start"] + PITCH_L / 2).round(2),
        "y_start": (d["y_start"] + PITCH_W / 2).round(2),
        "x_end": (pd.Series(x_end, index=d.index) + PITCH_L / 2).round(2),
        "y_end": (pd.Series(y_end, index=d.index) + PITCH_W / 2).round(2),
        "outcome": d["pass_outcome"].fillna(d["end_type"]).fillna("n/a"),
        "phase": d["team_in_possession_phase_type"],
        "phase_against": d["team_out_of_possession_phase_type"],
        # a pass carries the xThreat of the option it aimed at; a run has its own
        "xthreat": d["player_targeted_xthreat"].where(is_pass, d["xthreat"].where(is_run)),
        "dangerous": d["player_targeted_dangerous"].where(is_pass, d["dangerous"].where(is_run)).astype("boolean"),
        "speed_band": d["speed_avg_band"],
        "subtype": d["event_subtype"].where(is_engagement | is_run),
        "lead_to_shot": d["lead_to_shot"].astype("boolean"),
        "targeted": d["targeted"].where(is_run).astype("boolean"),
        "received": d["received"].where(is_run).astype("boolean"),
    }).sort_values("ts", kind="stable").reset_index(drop=True)
    # actions keep the numbering they had before runs existed (e), runs get their own sequence (r)
    is_run = out["type"].eq("run")
    ids = pd.Series(index=out.index, dtype=object)
    ids[~is_run] = [f"{match_id}-e{i:05d}" for i in range(1, int((~is_run).sum()) + 1)]
    ids[is_run] = [f"{match_id}-r{i:05d}" for i in range(1, int(is_run.sum()) + 1)]
    out.insert(1, "event_id", ids)
    return out


def build_match(info: dict, match_id: str, tracking: pd.DataFrame) -> pd.DataFrame:
    """One row of match facts: league, teams, colours, score, periods (in ts), attack directions."""
    per = tracking.groupby("period")["ts"].agg(["min", "max"])
    side = info["home_team_side"]
    home, away = info["home_team"], info["away_team"]
    edition = info.get("competition_edition") or {}
    return pd.DataFrame([{
        "match_id": match_id,
        "competition": (edition.get("competition") or {}).get("name"),
        "season": (edition.get("season") or {}).get("name"),
        "round": (info.get("competition_round") or {}).get("name"),
        "kickoff_utc": info.get("date_time"),
        "stadium": (info.get("stadium") or {}).get("name"),
        "home_team": home["name"], "away_team": away["name"],
        "home_team_short": home.get("short_name") or home["name"],
        "away_team_short": away.get("short_name") or away["name"],
        "home_color": (info.get("home_team_kit") or {}).get("jersey_color"),
        "away_color": (info.get("away_team_kit") or {}).get("jersey_color"),
        "home_score": int(info["home_team_score"]), "away_score": int(info["away_team_score"]),
        "pitch_length": float(info["pitch_length"]), "pitch_width": float(info["pitch_width"]),
        "p1_start_ts": int(per.loc[1, "min"]), "p1_end_ts": int(per.loc[1, "max"]),
        "p2_start_ts": int(per.loc[2, "min"]), "p2_end_ts": int(per.loc[2, "max"]),
        "home_side_p1": side[0], "home_side_p2": side[1],
    }])