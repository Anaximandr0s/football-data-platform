"""bronze_to_silver.py: clean the bronze tables of one or more matches and write the Silver Iceberg tables.

    python -m spark.silver.bronze_to_silver --match m001 m002     # explicit matches
    python -m spark.silver.bronze_to_silver --all                 # every match found in bronze
    python -m spark.silver.bronze_to_silver --match m001 --dry-run   # clean + check, write nothing

Reads   s3a://bronze/<table>/match_id=<id>/   (tracking, events, ball, players, matches)
Writes  <catalog>.<namespace>.<table>         (default lake.silver.*, files in s3a://silver/warehouse)

Per match: read -> clean (spark/silver/transforms.py) -> check (spark/silver/checks.py) -> write.
The write replaces the match's partition, so running the job again gives the same tables: no
duplicates, other matches untouched. If a check fails the match is not written and the exit code is 1.
"""
import argparse
import os
import sys
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from spark.silver import checks, config, transforms
from spark.silver.session import build_spark


def list_matches(bronze_uri: str) -> list[str]:
    """Match ids that have a `matches` folder in bronze."""
    if bronze_uri.startswith("s3a://"):
        import boto3  # same dependency and credentials as ingestion/check_bronze.py
        bucket, _, prefix = bronze_uri.removeprefix("s3a://").partition("/")
        s3 = boto3.client("s3", endpoint_url=config.S3_ENDPOINT_URL, region_name="us-east-1",
                          aws_access_key_id=config.S3_USER, aws_secret_access_key=config.S3_PASSWORD)
        base = f"{prefix.strip('/')}/matches/".lstrip("/")
        resp = s3.list_objects_v2(Bucket=bucket, Prefix=base, Delimiter="/")
        return sorted(p["Prefix"].rstrip("/").split("match_id=")[-1] for p in resp.get("CommonPrefixes", []))
    root = Path(bronze_uri.removeprefix("file://")) / "matches"
    return sorted(p.name.split("match_id=")[-1] for p in root.glob("match_id=*"))


def read_bronze(spark: SparkSession, bronze_uri: str, table: str, match_id: str) -> DataFrame:
    """One match folder of one table. Read per match (the guide's advice): the folder is named
    match_id=... and the files also contain a match_id column. ingest_date is path-only: dropped."""
    path = f"{bronze_uri.rstrip('/')}/{table}/match_id={match_id}/"
    return spark.read.parquet(path).drop("ingest_date")


def write_table(spark: SparkSession, df: DataFrame, table: str) -> None:
    """Create the Iceberg table (partitioned by match_id) or replace this match's partition."""
    full = f"{config.CATALOG}.{config.NAMESPACE}.{table}"
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {config.CATALOG}.{config.NAMESPACE}")
    if spark.catalog.tableExists(full):
        df.writeTo(full).overwritePartitions()
    else:
        (df.writeTo(full).using("iceberg").partitionedBy(F.col("match_id"))
           .tableProperty("format-version", "2").create())


def process_match(spark: SparkSession, match_id: str, bronze_uri: str, manifest_dir: Path,
                  dry_run: bool, events_direction: str = config.EVENTS_DIRECTION) -> bool:
    raw = {t: read_bronze(spark, bronze_uri, t, match_id) for t in config.BRONZE_TABLES}
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

    metrics = checks.measure(raw_counts, silver["tracking"], silver["events"], silver["ball"],
                             players, matches)
    manifest = checks.load_manifest(match_id, manifest_dir)
    ok = checks.report(match_id, metrics, checks.evaluate(metrics, manifest), manifest is not None)
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
                    help="guide = rule of the silver guide (default); per_team = mirror AWAY events only")
    ap.add_argument("--dry-run", action="store_true", help="clean and check, write nothing (no Iceberg needed)")
    ap.add_argument("--packages", default=None,
                    help="Spark Maven packages; '' for none (default: hadoop-aws + Iceberg runtime)")
    a = ap.parse_args()
    if bool(a.match) == a.all:
        ap.error("give --match ID [ID ...] or --all")

    spark = build_spark(packages=a.packages, iceberg=not a.dry_run)
    matches = a.match or list_matches(a.bronze_uri)
    if not matches:
        sys.exit("no match found in bronze")
    results = {m: process_match(spark, m, a.bronze_uri, a.manifest_dir, a.dry_run, a.events_direction) for m in matches}
    spark.stop()
    print("\nsummary:", {m: ("OK" if ok else "FAILED") for m, ok in results.items()})
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    main()
