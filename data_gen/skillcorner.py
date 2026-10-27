"""Convert a SkillCorner open-data match to OUR schema (real source, pseudonymised).

- Real names/teams are NEVER written out (course rule: fictional names only).
- Tracking 10 Hz centred coordinates -> 1 Hz, pitch metres with origin bottom-left.
- Speed is computed from positions (not provided by SkillCorner): 3-point median, capped at 40 km/h.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

from data_gen.common import EVENT_COLS, MAX_SPEED_KMH, PITCH_L, PITCH_W, TRACKING_COLS

FPS = 10


def load_match_info(match_dir: Path, sc_id: int) -> dict:
    return json.loads((match_dir / f"{sc_id}_match.json").read_text())


def build_players(info: dict, match_id: str, seed: int):
    """Pseudonymise: SkillCorner player id -> H01../A01.., Faker name."""
    Faker.seed(seed)
    fake = Faker("en_GB")
    home_id = info["home_team"]["id"]
    rows, idmap, spans = [], {}, {}
    for side, prefix in (("HOME", "H"), ("AWAY", "A")):
        team = [p for p in info["players"]
                if p.get("playing_time") and (p["team_id"] == home_id) == (side == "HOME")
                and p["playing_time"].get("total") and p["playing_time"]["total"].get("start_frame") is not None]
        team.sort(key=lambda p: (p["playing_time"]["total"]["start_frame"], p["number"]))
        for i, p in enumerate(team, start=1):
            pid = f"{prefix}{i:02d}"
            idmap[p["id"]] = (pid, side)
            tt = p["playing_time"]["total"]
            spans[p["id"]] = (tt["start_frame"], tt["end_frame"])
            rows.append((match_id, pid, side, fake.name(), p["player_role"]["position_group"], p["number"]))
    cols = ["match_id", "player_id", "team_id", "name", "position", "shirt_number"]
    return pd.DataFrame(rows, columns=cols), idmap, spans


def parse_tracking(lines, info, idmap, spans, match_id: str) -> pd.DataFrame:
    """lines: iterable of JSON lines. Keeps 1 frame out of 10, players on the pitch only."""
    first = min(p["start_frame"] for p in info["match_periods"])
    rows = []
    for line in lines:
        fr = json.loads(line)
        f = fr.get("frame")
        if f is None or fr.get("timestamp") is None or (f - first) % FPS or f < first:
            continue
        ts = (f - first) // FPS
        for p in fr["player_data"]:
            pid = p.get("player_id")
            if pid not in idmap or p.get("x") is None:
                continue
            s, e = spans[pid]
            if not (s <= f <= e):
                continue
            rows.append((match_id, idmap[pid][0], ts,
                         min(max(p["x"] + PITCH_L / 2, 0.0), PITCH_L),
                         min(max(p["y"] + PITCH_W / 2, 0.0), PITCH_W)))
    df = pd.DataFrame(rows, columns=["match_id", "player_id", "ts", "x", "y"])
    df = df.sort_values(["player_id", "ts"]).reset_index(drop=True)
    g = df.groupby("player_id")
    step = np.hypot(g["x"].diff(), g["y"].diff())
    gap = g["ts"].diff()
    df["speed_kmh"] = np.where(gap == 1, step * 3.6, np.nan)
    df["speed_kmh"] = (df.groupby("player_id")["speed_kmh"]
                         .transform(lambda s: s.rolling(3, center=True, min_periods=1).median())
                         .fillna(0.0).clip(upper=MAX_SPEED_KMH))
    df[["x", "y", "speed_kmh"]] = df[["x", "y", "speed_kmh"]].round(2)
    return df.sort_values(["ts", "player_id"])[TRACKING_COLS].reset_index(drop=True)


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
    first = min(p["start_frame"] for p in info["match_periods"])
    home_id = info["home_team"]["id"]
    goal_idx = _goal_shot_index(raw, home_id)
    d = raw[raw["player_id"].isin(idmap.keys())].copy()
    pp = d["event_type"] == "player_possession"
    eng = d["event_type"] == "on_ball_engagement"
    kind = pd.Series(np.nan, index=d.index, dtype=object)
    kind[pp & (d["end_type"] == "pass")] = "pass"
    kind[pp & (d["end_type"] == "shot")] = "shot"
    kind[d.index.isin(goal_idx)] = "goal"
    kind[eng] = "pressure"                                                # pressing actions
    kind[eng & d["end_type"].isin(["direct_regain", "direct_disruption"])] = "tackle"
    kind[eng & (d["end_type"] == "foul_committed")] = "foul"
    d["type"] = kind
    d = d[d["type"].notna()]
    # pass destination = where the targeted player received it; else possession end point
    x_end = np.where(d["type"].eq("pass") & d["player_targeted_x_reception"].notna(),
                     d["player_targeted_x_reception"], d["x_end"])
    y_end = np.where(d["type"].eq("pass") & d["player_targeted_y_reception"].notna(),
                     d["player_targeted_y_reception"], d["y_end"])
    out = pd.DataFrame({
        "match_id": match_id,
        "ts": ((d["frame_start"] - first) // FPS).clip(lower=0).astype(int),
        "player_id": d["player_id"].map(lambda i: idmap[i][0]),
        "team_id": np.where(d["team_id"] == home_id, "HOME", "AWAY"),
        "type": d["type"],
        "x_start": (d["x_start"] + PITCH_L / 2).clip(0, PITCH_L).round(2),
        "y_start": (d["y_start"] + PITCH_W / 2).clip(0, PITCH_W).round(2),
        "x_end": (pd.Series(x_end, index=d.index) + PITCH_L / 2).clip(0, PITCH_L).round(2),
        "y_end": (pd.Series(y_end, index=d.index) + PITCH_W / 2).clip(0, PITCH_W).round(2),
        "outcome": d["pass_outcome"].fillna(d["end_type"]).fillna("n/a"),
    }).sort_values("ts").reset_index(drop=True)
    out.insert(1, "event_id", [f"{match_id}-e{i:05d}" for i in range(1, len(out) + 1)])
    return out[EVENT_COLS]
