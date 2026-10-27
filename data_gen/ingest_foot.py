"""ingest_foot.py: generate the match data (players, tracking, events) as Parquet.

  python -m data_gen.ingest_foot --source sim --match m001 --seed 42
  python -m data_gen.ingest_foot --source skillcorner --match m002 --sc-id 1925299
"""
import argparse
import json
from pathlib import Path

from data_gen.common import GENERATED_DIR, RAW_DIR


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--source", choices=["sim", "skillcorner"], default="sim")
    ap.add_argument("--match", default="m001", help="our match_id")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--sc-id", type=int, help="SkillCorner match id (source=skillcorner)")
    ap.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    ap.add_argument("--out", type=Path, default=GENERATED_DIR)
    a = ap.parse_args()

    if a.source == "sim":
        from data_gen.sim import simulate_match
        players, tracking, events = simulate_match(a.match, a.seed)
    else:
        from data_gen import skillcorner as sc
        if not a.sc_id:
            ap.error("--sc-id is required with --source skillcorner")
        mdir = a.raw_dir / str(a.sc_id)
        info = sc.load_match_info(mdir, a.sc_id)
        players, idmap, spans = sc.build_players(info, a.match, a.seed)
        with open(mdir / f"{a.sc_id}_tracking_extrapolated.jsonl") as fh:
            tracking = sc.parse_tracking(fh, info, idmap, spans, a.match)
        events = sc.parse_events(mdir / f"{a.sc_id}_dynamic_events.csv", info, idmap, a.match)

    out = a.out / a.match
    out.mkdir(parents=True, exist_ok=True)
    players.to_parquet(out / "players.parquet", index=False)
    tracking.to_parquet(out / "tracking.parquet", index=False)
    events.to_parquet(out / "events.parquet", index=False)
    manifest = {"match_id": a.match, "source": a.source, "seed": a.seed,
                "players": len(players), "tracking_rows": len(tracking),
                "events": len(events), "max_ts": int(tracking["ts"].max()),
                "max_speed_kmh": float(tracking["speed_kmh"].max()),
                "players_per_second_min": int(tracking.groupby("ts").size().min()),
                "players_per_second_max": int(tracking.groupby("ts").size().max())}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
