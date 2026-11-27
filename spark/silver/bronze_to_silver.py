"""bronze_to_silver.py: clean the bronze tables of one or more matches and write the Silver Iceberg tables.

    python -m spark.silver.bronze_to_silver --match m001 m002     # explicit matches
    python -m spark.silver.bronze_to_silver --all                 # every match found in bronze
    python -m spark.silver.bronze_to_silver --match m001 --dry-run   # clean + check, write nothing
    python -m spark.silver.bronze_to_silver --match m001 --replay m001-20261117T120000Z   # this replay

Reads   s3a://bronze/<table>/match_id=<id>/replay_id=<replay>/   one replay only: the one given, else the latest
        complete one (its tracking reaches the match's last second). Older replays and the files written before
        replay folders existed stay in Bronze as raw history and are not read.
Writes  <catalog>.<namespace>.<table>         (default lake.silver.*, files in s3a://silver/warehouse)

Per match: read -> clean (spark/silver/transforms.py) -> check (spark/silver/checks.py) -> write.
The write replaces the match's partition, so running the job again gives the same tables: no
duplicates, other matches untouched. If a check fails the match is not written and the exit code is 1.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from pyspark.errors import AnalysisException
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from ingestion import replay_ids
from spark.silver import checks, config, transforms
from spark.silver.session import build_spark


def list_matches(spark: SparkSession, bronze_uri: str) -> list[str]:
    """Match ids that have a `matches` folder in bronze. Uses Spark's own Hadoop filesystem, so it works
    for s3a:// and file:// alike and needs no extra Python package inside the Spark container."""
    names = _children(spark, f"{bronze_uri.rstrip('/')}/matches")
    return sorted(n.split("match_id=")[-1] for n in names if n.startswith("match_id="))


def _children(spark: SparkSession, uri: str) -> list[str]:
    jvm = spark._jvm
    path = jvm.org.apache.hadoop.fs.Path(uri)
    fs = path.getFileSystem(spark._jsc.hadoopConfiguration())
    return [st.getPath().getName() for st in fs.listStatus(path)] if fs.exists(path) else []


def replays_in_bronze(spark: SparkSession, bronze_uri: str, match_id: str) -> list[str]:
    """The replay folders of a match (its `matches` table) that can make a match: not partial (started after
    kick-off, ingestion/replay_ids.py), not without id. Replay ids, any order."""
    names = _children(spark, f"{bronze_uri.rstrip('/')}/matches/match_id={match_id}")
    ids = [n.split("replay_id=", 1)[1] for n in names if n.startswith("replay_id=") and n != "replay_id=none"]
    return [r for r in ids if not replay_ids.is_partial(r)]


def choose_replay(replays: list[str], is_complete) -> str | None:
    """The newest complete replay. A replay id ends with its start time (m001-20261117T120000Z): sorting the ids
    sorts the replays in time."""
    return next((r for r in sorted(replays, reverse=True) if is_complete(r)), None)


def replay_complete(spark: SparkSession, bronze_uri: str, match_id: str, replay_id: str) -> bool:
    """The replay sent the match's last second: max(tracking.ts) >= matches.p2_end_ts."""
    try:
        end = read_bronze(spark, bronze_uri, "matches", match_id, replay_id).agg(F.max("p2_end_ts")).first()[0]
        last = read_bronze(spark, bronze_uri, "tracking", match_id, replay_id).agg(F.max("ts")).first()[0]
    except AnalysisException as exc:      # a table's folder is missing: the replay is incomplete
        print(f"{match_id} {replay_id}: unreadable ({type(exc).__name__}), not complete", file=sys.stderr)
        return False
    return end is not None and last is not None and last >= end


def read_bronze(spark: SparkSession, bronze_uri: str, table: str, match_id: str, replay_id: str) -> DataFrame:
    """One replay of one match of one table. The files also contain match_id and kafka_replay_id columns;
    ingest_date is path-only: dropped."""
    path = f"{bronze_uri.rstrip('/')}/{table}/match_id={match_id}/replay_id={replay_id}/"
    # files written before a column was added to the contract lack it: merge so it reads as null there
    return spark.read.option("mergeSchema", "true").parquet(path).drop("ingest_date")


def write_table(spark: SparkSession, df: DataFrame, table: str) -> None:
    """Create the Iceberg table (partitioned by match_id) or replace this match's partition."""
    full = f"{config.CATALOG}.{config.NAMESPACE}.{table}"
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {config.CATALOG}.{config.NAMESPACE}")
    if spark.catalog.tableExists(full):
        existing = set(spark.table(full).columns)
        for field in df.schema.fields:
            if field.name not in existing:
                spark.sql(f"ALTER TABLE {full} ADD COLUMN {field.name} {field.dataType.simpleString()}")
        df.writeTo(full).overwritePartitions()
    else:
        (df.writeTo(full).using("iceberg").partitionedBy(F.col("match_id"))
           .tableProperty("format-version", "2").create())


def write_quality(match_id: str, metrics: dict, manifest: dict | None, ok: bool, written: bool, replay: dict) -> None:
    at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: UP017 - the Spark image runs Python 3.10
    config.QUALITY_DIR.mkdir(parents=True, exist_ok=True)
    path = config.QUALITY_DIR / f"silver_{match_id}.json"
    path.write_text(json.dumps(checks.quality_report(match_id, metrics, manifest, ok, written, at) | replay, indent=1),
                    encoding="utf-8")
    print(f"quality report: {path}")


def process_match(spark: SparkSession, match_id: str, bronze_uri: str, manifest_dir: Path,
                  dry_run: bool, events_direction: str = config.EVENTS_DIRECTION, replay_id: str | None = None) -> bool:
    replays = replays_in_bronze(spark, bronze_uri, match_id)
    if replay_id is None:
        replay_id = choose_replay(replays, lambda r: replay_complete(spark, bronze_uri, match_id, r))
    if replay_id is not None and replay_ids.is_partial(replay_id):
        print(f"{match_id}: {replay_id} started after kick-off: a partial replay is live only, Silver needs a whole "
              f"match (replay it from kick-off)", file=sys.stderr)
        return False
    if replay_id is None or replay_id not in replays:
        print(f"{match_id}: no complete replay in bronze's replay folders "
              f"({len(replays)} replay(s) found{', not ' + replay_id if replay_id else ''}): replay the match once "
              f"(make replay MATCH={match_id})", file=sys.stderr)
        return False
    print(f"{match_id}: reading replay {replay_id} ({len(replays)} replay(s) in bronze)")
    raw = {t: read_bronze(spark, bronze_uri, t, match_id, replay_id) for t in config.BRONZE_TABLES}
    raw_counts = {t: df.count() for t, df in raw.items()}
    if not all(raw_counts.values()):
        print(f"{match_id}: bronze is empty for {[t for t, n in raw_counts.items() if not n]}: "
              f"replay the match first (make replay MATCH={match_id})", file=sys.stderr)
        return False

    players = transforms.clean_players(raw["players"]).cache()
    matches = transforms.clean_matches(raw["matches"]).cache()
    silver = {
        "players": players,
        "matches": matches,
        "tracking": transforms.clean_tracking(raw["tracking"], players, matches).cache(),
        "events": transforms.clean_events(raw["events"], matches, events_direction).cache(),
        "ball": transforms.clean_ball(raw["ball"], matches).cache(),
    }
    silver = {t: df.withColumn("replay_id", F.lit(replay_id)) for t, df in silver.items()}   # where it comes from

    print(f"\nevents direction used for {match_id}: {events_direction}")
    over_max = transforms.speeds_over_max(raw["tracking"])
    metrics = checks.measure(raw_counts, silver["tracking"], silver["events"], silver["ball"],
                             players, matches, speed_over_max=over_max)
    manifest = checks.load_manifest(match_id, manifest_dir)
    ok = checks.report(match_id, metrics, checks.evaluate(metrics, manifest), manifest is not None)
    write_quality(match_id, metrics, manifest, ok, written=ok and not dry_run,
                  replay={"replay_id": replay_id, "replays_in_bronze": len(replays)})
    if not ok:
        print(f"{match_id}: a check failed, nothing written", file=sys.stderr)
    elif dry_run:
        print(f"{match_id}: dry run, nothing written")
    else:
        for table, df in silver.items():
            write_table(spark, df, table)
            full = f"{config.CATALOG}.{config.NAMESPACE}.{table}"
            n = spark.table(full).filter(F.col("match_id") == match_id).count()
            print(f"wrote {full}: {n} rows for {match_id}")
    for df in silver.values():
        df.unpersist()
    return ok


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--match", nargs="+", help="match ids, e.g. m001 m002")
    ap.add_argument("--all", action="store_true", help="every match found in bronze")
    ap.add_argument("--bronze-uri", default=config.BRONZE_URI, help="default %(default)s")
    ap.add_argument("--manifest-dir", type=Path, default=config.MANIFEST_DIR,
                    help="ingestion manifests, to compare counts (skipped if absent)")
    ap.add_argument("--events-direction", choices=transforms.EVENT_DIRECTIONS, default=config.EVENTS_DIRECTION,
                    help="per_team = mirror AWAY events only (default); guide = mirror every event like tracking")
    ap.add_argument("--replay", help="the replay to read (one match only); default: the latest complete one")
    ap.add_argument("--dry-run", action="store_true", help="clean and check, write nothing (no Iceberg needed)")
    ap.add_argument("--packages", default=None,
                    help="Spark Maven packages; '' for none (default: hadoop-aws + Iceberg runtime)")
    a = ap.parse_args()
    if bool(a.match) == a.all:
        ap.error("give --match ID [ID ...] or --all")
    if a.replay and (not a.match or len(a.match) != 1):
        ap.error("--replay goes with exactly one --match")

    spark = build_spark(packages=a.packages, iceberg=not a.dry_run)
    matches = a.match or list_matches(spark, a.bronze_uri)
    if not matches:
        sys.exit("no match found in bronze")
    results = {m: process_match(spark, m, a.bronze_uri, a.manifest_dir, a.dry_run, a.events_direction, a.replay)
               for m in matches}
    spark.stop()
    print("\nsummary:", {m: ("OK" if ok else "FAILED") for m, ok in results.items()})
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    main()
