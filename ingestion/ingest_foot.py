"""ingest_foot.py (step 2): raw SkillCorner files -> the platform's five Parquet tables.

    python -m ingestion.ingest_foot --match m001 --sc-id 1874553

Reads   data/raw/skillcorner/<sc-id>/   (written by download_foot.py)
Writes  data/prepared/<match>/          players, tracking, events, ball, matches (.parquet) + manifest.json

Done here (structure only)             Never done here (Silver's job)
- 10 Hz -> 1 Hz (1 frame out of 10)    - clipping of positions or speeds
- one row per player per second        - smoothing, direction flip at half-time
- origin bottom-left, metres           - deduplication
- player ids H01.. / A01.. (names kept)
- speed derived from positions
- events mapped to our vocabulary: pass, shot, goal, tackle, foul, pressure,
  and off-ball runs as type run (not an action: never counted with them)

The SkillCorner format knowledge lives in skillcorner.py; the table schemas in schemas.py.
Names, teams, league and kit colours are copied from match.json as they are.
"""
import argparse
import json
import sys
from pathlib import Path

from ingestion.config import PITCH_L, PITCH_W, PREPARED_DIR, RAW_DIR
from ingestion.schemas import write_parquet
from ingestion.skillcorner import build_match, build_players, parse_events, parse_tracking


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--match", required=True, help="our match id, e.g. m001")
    ap.add_argument("--sc-id", type=int, required=True, help="SkillCorner match id")
    ap.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    ap.add_argument("--out", type=Path, default=PREPARED_DIR)
    a = ap.parse_args()

    src = a.raw_dir / str(a.sc_id)
    paths = {"info": src / f"{a.sc_id}_match.json",
             "events": src / f"{a.sc_id}_dynamic_events.csv",
             "tracking": src / f"{a.sc_id}_tracking_extrapolated.jsonl"}
    missing = [p.name for p in paths.values() if not p.exists()]
    if missing:
        sys.exit(f"missing in {src}: {', '.join(missing)}\n"
                 f"run: python -m ingestion.download_foot {a.sc_id}")

    info = json.loads(paths["info"].read_text(encoding="utf-8"))
    if (info["pitch_length"], info["pitch_width"]) != (PITCH_L, PITCH_W):
        sys.exit(f"pitch is {info['pitch_length']}x{info['pitch_width']}, the platform expects "
                 f"{PITCH_L}x{PITCH_W}: pick another match")

    players, idmap, spans = build_players(info, a.match)
    with open(paths["tracking"], encoding="utf-8") as fh:
        tracking, ball, drops = parse_tracking(fh, info, idmap, spans, a.match)
    events = parse_events(paths["events"], info, idmap, a.match)
    match = build_match(info, a.match, tracking)

    out = a.out / a.match
    out.mkdir(parents=True, exist_ok=True)
    for name, df in (("players", players), ("tracking", tracking), ("events", events),
                     ("ball", ball), ("matches", match)):
        write_parquet(df, name, out / f"{name}.parquet")

    per_second = tracking.groupby("ts").size()
    goals = events.loc[events["type"] == "goal", "team_id"].value_counts()
    outside = ((tracking["x"] < 0) | (tracking["x"] > PITCH_L)
               | (tracking["y"] < 0) | (tracking["y"] > PITCH_W))
    manifest = {
        "match_id": a.match, "source": "skillcorner", "source_match_id": a.sc_id,
        "teams": [info["home_team"]["name"], info["away_team"]["name"]],
        "players": len(players), "tracking_rows": len(tracking), "events": len(events),
        "ball_rows": len(ball), "max_ts": int(tracking["ts"].max()),
        "seconds_with_data": int(per_second.size),
        "players_per_second_min": int(per_second.min()),
        "players_per_second_max": int(per_second.max()),
        "rows_outside_pitch": int(outside.sum()),
        "rows_speed_over_40": int((tracking["speed_kmh"] > 40).sum()),
        "rows_speed_null": int(tracking["speed_kmh"].isna().sum()),
        "rows_detected": int(tracking["is_detected"].eq(True).sum()),
        "ball_rows_with_possession": int(ball["possession"].notna().sum()),
        "possession_seconds_home_away": [int(ball["possession"].eq("HOME").sum()),
                                         int(ball["possession"].eq("AWAY").sum())],
        "events_by_type": {k: int(v) for k, v in events["type"].value_counts().items()},
        "goals_derived_home_away": [int(goals.get("HOME", 0)), int(goals.get("AWAY", 0))],
        "score_real_home_away": [int(info["home_team_score"]), int(info["away_team_score"])],
        "dropped_rows": dict(drops),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    if manifest["goals_derived_home_away"] != manifest["score_real_home_away"]:
        print("WARNING: derived goals differ from the real score", file=sys.stderr)


if __name__ == "__main__":
    main()