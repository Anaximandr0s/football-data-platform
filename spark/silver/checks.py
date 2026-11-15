"""checks.py: the numbers the guide asks us to get back, computed on the cleaned DataFrames BEFORE
anything is written. The job stops (exit code 1) and writes nothing if a hard check fails.

These are the Silver job's own sanity gates. They are not the Soda checks of FOO-05 (22 players per
second, speed <= 40, event types...), which run later on the Silver tables.
"""
import json
from pathlib import Path

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from spark.silver.config import PITCH_L, PITCH_W


def measure(raw_counts: dict[str, int], tracking: DataFrame, events: DataFrame, ball: DataFrame,
            players: DataFrame, matches: DataFrame) -> dict:
    """All metrics in a few Spark jobs. `raw_counts` = rows read from bronze, per table."""
    t = tracking.agg(
        F.count("*").alias("rows"),
        F.countDistinct("player_id", "ts").alias("distinct_keys"),
        F.sum(F.col("was_corrected").cast("int")).alias("corrected"),
        F.sum(F.col("speed_kmh").isNull().cast("int")).alias("speed_null"),
        F.sum(F.col("is_sprint").cast("int")).alias("sprints"),
        F.sum(F.col("is_after_gap").cast("int")).alias("after_gap"),
        F.sum(F.col("team_id").isNull().cast("int")).alias("team_null"),
        F.sum(((F.col("x") < 0) | (F.col("x") > PITCH_L) | (F.col("y") < 0)
               | (F.col("y") > PITCH_W)).cast("int")).alias("outside_after"),
        F.max("speed_kmh").alias("speed_max"),
        F.countDistinct("ts").alias("seconds"),
    ).first()
    e = events.agg(F.count("*").alias("rows"), F.countDistinct("event_id").alias("distinct_keys")).first()
    b = ball.agg(F.count("*").alias("rows"), F.countDistinct("ts").alias("distinct_keys")).first()
    p = players.agg(F.count("*").alias("rows"), F.countDistinct("match_id", "player_id").alias("distinct_keys")).first()
    m = matches.first()
    shots = {r["team_id"]: [r["avg_x"], r["n"]] for r in
             events.filter(F.col("type").isin("shot", "goal")).groupBy("team_id")
             .agg(F.avg("x_start").alias("avg_x"), F.count("*").alias("n")).collect()}
    goals = {r["team_id"]: r["n"] for r in
             events.filter(F.col("type") == "goal").groupBy("team_id").agg(F.count("*").alias("n")).collect()}
    return {
        "bronze_rows": dict(raw_counts),
        "rows": {"tracking": t["rows"], "events": e["rows"], "ball": b["rows"],
                 "players": p["rows"], "matches": matches.count()},
        "keys_unique": {"tracking": t["rows"] == t["distinct_keys"], "events": e["rows"] == e["distinct_keys"],
                        "ball": b["rows"] == b["distinct_keys"], "players": p["rows"] == p["distinct_keys"]},
        "tracking": {"was_corrected": t["corrected"] or 0, "speed_null": t["speed_null"] or 0,
                     "sprints": t["sprints"] or 0, "after_gap": t["after_gap"] or 0,
                     "team_null": t["team_null"] or 0, "outside_after_clip": t["outside_after"] or 0,
                     "speed_max": t["speed_max"], "seconds_with_data": t["seconds"]},
        "shot_avg_x": shots,      # {team: [mean x_start of its shots and goals, how many]}
        "goals_home_away": [int(goals.get("HOME", 0)), int(goals.get("AWAY", 0))],
        "score_home_away": [int(m["home_score"]), int(m["away_score"])] if m else None,
    }


def load_manifest(match_id: str, manifest_dir: Path) -> dict | None:
    path = manifest_dir / match_id / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def evaluate(metrics: dict, manifest: dict | None) -> list[tuple[str, bool, str]]:
    """Returns (check name, passed, detail). Pure Python, so it is unit-tested without Spark."""
    out: list[tuple[str, bool, str]] = []
    for table, ok in metrics["keys_unique"].items():
        out.append((f"{table}: one row per key", ok, ""))
    tr = metrics["tracking"]
    out.append(("tracking: every row has a team_id", tr["team_null"] == 0, f"{tr['team_null']} null"))
    out.append(("tracking: all positions inside the pitch after clipping", tr["outside_after_clip"] == 0,
                f"{tr['outside_after_clip']} outside"))
    goals, score = metrics["goals_home_away"], metrics["score_home_away"]
    out.append(("events: goals equal the final score", goals == score, f"goals={goals} score={score}"))

    # frame gate: in the Silver frame HOME attacks toward x = 105 and AWAY toward x = 0, so HOME's shots must sit on the
    # right half on average and AWAY's on the left half (judged only with 3 shots or more: a mean of 1 or 2 shots means little)
    for team, ok_side in (("HOME", lambda x: x > 52.5), ("AWAY", lambda x: x < 52.5)):
        avg, n = metrics.get("shot_avg_x", {}).get(team, [None, 0])
        if avg is not None and n >= 3:
            out.append((f"events: {team} shots are on the half it attacks (frame of Silver)", ok_side(avg),
                        f"mean x = {avg:.1f} over {n} shots"))

    if manifest is None:
        return out
    exp = {"tracking": manifest["tracking_rows"], "events": manifest["events"], "ball": manifest["ball_rows"],
           "players": manifest["players"], "matches": 1}
    for table, want in exp.items():
        got = metrics["rows"][table]
        out.append((f"{table}: rows after dedup = ingestion manifest", got == want, f"{got} vs {want}"))
    out.append(("tracking: was_corrected rows = manifest rows_outside_pitch",
                tr["was_corrected"] == manifest["rows_outside_pitch"],
                f"{tr['was_corrected']} vs {manifest['rows_outside_pitch']}"))
    out.append(("tracking: null speeds untouched (null stays null)",
                tr["speed_null"] == manifest["rows_speed_null"],
                f"{tr['speed_null']} vs {manifest['rows_speed_null']}"))
    return out


def report(match_id: str, metrics: dict, results: list[tuple[str, bool, str]], has_manifest: bool) -> bool:
    """Print the report, return True if every check passed."""
    print(f"\n=== Silver report {match_id} ===")
    print("bronze rows read :", metrics["bronze_rows"])
    print("silver rows      :", metrics["rows"])
    print("tracking         :", metrics["tracking"])
    if not has_manifest:
        print("(no ingestion manifest found: row counts were not compared with the source)")
    ok = True
    for name, passed, detail in results:
        print(f"  {'OK  ' if passed else 'FAIL'} {name}" + (f"  [{detail}]" if detail else ""))
        ok &= passed
    return ok
