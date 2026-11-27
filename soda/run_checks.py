"""run_checks.py: run the Soda checks (SodaCL files in soda/checks/) on the Silver and Gold layers.

    python soda/run_checks.py --layer silver            # checks/silver.yml on the Silver Iceberg tables
    python soda/run_checks.py --layer gold              # checks/gold.yml on data/football.duckdb
    python soda/run_checks.py --layer all               # both (Silver first)
    python soda/run_checks.py --layer silver --demo-failure   # corrupt a copy ON PURPOSE, show the checks catch it
    python soda/run_checks.py --layer silver --inject-damage  # the same damage, reported as a real failure (Dagster)

Normally run through `make soda` / `make soda-silver` / `make soda-gold` / `make soda-demo` (service `soda`).

How it reads the data: one in-memory DuckDB connection per layer, handed to Soda (`add_duckdb_connection`).
  Silver: views silver_tracking, silver_events, silver_ball, silver_players, silver_matches over the Iceberg folders
          (iceberg_scan) or, with --silver-reader parquet, over Parquet files <root>/<table>/*.parquet.
  Gold:   the DuckDB file written by dbt, attached READ ONLY; views gold_* with the same names as the tables.
Nothing is ever written to Silver or Gold. Each run writes data/soda/<layer>.json (read by the dashboard) and
exits 0 only if no check failed and no check could not run.
"""

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import duckdb
from ruamel.yaml import YAML  # installed with soda-core
from soda.scan import Scan

ROOT = Path(__file__).resolve().parents[1]
CHECKS_DIR = Path(__file__).resolve().parent / "checks"
SILVER_TABLES = ("tracking", "events", "ball", "players", "matches")
GOLD_TABLES = (
    "gold_player_match_stats",
    "gold_team_match_stats",
    "gold_zone_occupancy",
    "gold_pass_network",
    "gold_shots",
    "gold_player_5min",
    "gold_match_timeline",
    "gold_player_card",
    "gold_team_shape",
    "gold_pressing",
    "gold_team_build_up",
    "gold_player_fatigue",
    "gold_space_control",
    "gold_team_profile",
    "gold_events",
    "gold_match_library",
    "gold_replay_frames",
)


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _load_s3(con: duckdb.DuckDBPyConnection) -> None:
    """httpfs + iceberg extensions and the MinIO settings (same environment variables as dbt/profiles.yml)."""
    for ext in ("httpfs", "iceberg"):
        con.execute(f"install {ext}")
        con.execute(f"load {ext}")
    settings = {
        "s3_endpoint": os.getenv("GOLD_S3_ENDPOINT", "localhost:9000"),
        "s3_url_style": "path",
        "s3_region": "us-east-1",
        "s3_access_key_id": os.getenv("MINIO_ROOT_USER", ""),
        "s3_secret_access_key": os.getenv("MINIO_ROOT_PASSWORD", ""),
    }
    for key, value in settings.items():
        con.execute(f"set {key} = {_sql_str(value)}")
    con.execute("set s3_use_ssl = false")
    con.execute("set unsafe_enable_version_guessing = true")  # iceberg_scan on a Hadoop-catalog folder


def silver_connection(reader: str, warehouse: str, namespace: str, parquet_root: str) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    if reader == "iceberg" or parquet_root.startswith("s3://"):
        _load_s3(con)
    for table in SILVER_TABLES:
        if reader == "iceberg":
            source = f"iceberg_scan('{warehouse}/{namespace}/{table}')"
        else:
            source = f"read_parquet('{parquet_root}/{table}/*.parquet')"
        con.execute(f"create view silver_{table} as select * from {source}")
    return con


def gold_connection(db_path: Path) -> duckdb.DuckDBPyConnection:
    if not db_path.exists():
        sys.exit(f"{db_path} does not exist: run `make gold` first (dbt build writes it)")
    con = duckdb.connect()
    con.execute(f"attach {_sql_str(str(db_path))} as gold_db (read_only)")
    for table in GOLD_TABLES:
        con.execute(f"create view {table} as select * from gold_db.main.{table}")
    return con


def corrupt(con: duckdb.DuckDBPyConnection, layer: str) -> list[str]:
    """--demo-failure: damage the VIEWS of this run (never the data) so that checks must fail."""
    if layer == "silver":
        con.execute("create table silver_tracking_ok as select * from silver_tracking")
        con.execute("""create or replace view silver_tracking as
            select * from silver_tracking_ok
            union all (select * from silver_tracking_ok limit 1)                                  -- a duplicate row
            union all (select * replace (131.5 as x, 61.0 as speed_kmh) from silver_tracking_ok
                       offset 10 limit 1)                                                         -- off the pitch, too fast""")
        return [
            "a duplicated tracking row (breaks: one row per key, 22 players per second, row counts)",
            "a position at x = 131.5 m and a speed of 61 km/h (breaks: inside the pitch, speed <= 40)",
        ]
    con.execute("create table gold_shots_ok as select * from gold_shots")
    con.execute("""create or replace view gold_shots as
        select * from gold_shots_ok
        where not (is_goal and ts = (select min(ts) from gold_shots_ok where is_goal))""")
    return ["a goal removed from gold_shots (breaks: goals equal the score of the team table)"]


def _rule_of(check: dict):
    """The rule of one check: Soda keeps its YAML snippet (`checks for <table>:` + one item) in `definition`."""
    try:
        doc = YAML(typ="safe").load(check.get("definition") or "")
        items = next(iter(doc.values()))
        return items[0] if items else None
    except Exception:  # noqa: BLE001 - an explanation is a bonus, never a reason to fail the run
        return None


def _fmt(value) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)


def _failed_rows_detail(con: duckdb.DuckDBPyConnection, check: dict, limit: int = 3) -> str | None:
    """Count and show the first rows that break a `failed rows` rule, by running its query again."""
    rule = _rule_of(check)
    if not isinstance(rule, dict) or "failed rows" not in rule:
        return None
    cfg = rule["failed rows"]
    sql = cfg.get("fail query") or f"select * from {check['table']} where {cfg['fail condition']}"
    sql = sql.strip().rstrip(";")
    total = con.execute(f"select count(*) from ({sql})").fetchone()[0]
    cur = con.execute(f"select * from ({sql}) limit {limit}")
    names = [d[0] for d in cur.description]
    shown = " | ".join(", ".join(f"{n}={_fmt(v)}" for n, v in zip(names, row, strict=True)) for row in cur.fetchall())
    return f"{total} failing row(s), first: {shown}"


def _schema_detail(log_text: str, name: str) -> str | None:
    """Soda writes why a schema check failed (missing / wrong type / forbidden column) under the check in its log."""
    lines = log_text.splitlines()
    for i, line in enumerate(lines):
        if line.rstrip().endswith("[FAILED]") and name in line:
            details = []
            for nxt in lines[i + 1 :]:
                body = nxt.split("INFO   |", 1)[-1]
                if not body.startswith(" " * 9):  # the details are indented deeper than the check line
                    break
                text = body.strip()
                if not text.startswith("schema_measured"):
                    details.append(text)
            return "; ".join(details) or None
    return None


def explain(con: duckdb.DuckDBPyConnection, check: dict, raw: dict, log_text: str) -> str:
    """Why a check did not pass, in one line (shown on the dashboard)."""
    detail = None
    try:
        detail = _failed_rows_detail(con, check) or _schema_detail(log_text, check["name"] or "")
    except duckdb.Error:
        pass
    if detail is None:
        value = (raw.get("diagnostics") or {}).get("value")
        if isinstance(value, (int, float)):
            detail = f"measured value: {_fmt(value)}"
    return (detail or "")[:500]


def run_layer(layer: str, con: duckdb.DuckDBPyConnection, out_dir: Path) -> tuple[Scan, dict]:
    scan = Scan()
    scan.set_scan_definition_name(f"football_{layer}")
    scan.set_data_source_name("football")
    scan.add_duckdb_connection(con, data_source_name="football")
    scan.add_sodacl_yaml_file(str(CHECKS_DIR / f"{layer}.yml"))
    scan.execute()

    checks = []
    log_text = scan.get_logs_text()
    for c in scan.get_scan_results().get("checks", []):
        entry = {
            "name": c.get("name") or c.get("definition"),
            "table": c.get("table"),
            "outcome": c.get("outcome") or "unknown",
            "definition": c.get("definition"),
            "detail": "",
        }
        if entry["outcome"] in ("fail", "warn"):
            entry["detail"] = explain(con, entry, c, log_text)
        checks.append(entry)
    summary = {
        "layer": layer,
        "finished_at_utc": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "passed": sum(c["outcome"] == "pass" for c in checks),
        "failed": sum(c["outcome"] == "fail" for c in checks),
        "warned": sum(c["outcome"] == "warn" for c in checks),
        "errors": len(scan.get_error_logs()),
        "checks": checks,
    }
    return scan, summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--layer", choices=["silver", "gold", "all"], required=True)
    ap.add_argument(
        "--silver-reader", choices=["iceberg", "parquet"], default=os.getenv("SODA_SILVER_READER", "iceberg")
    )
    ap.add_argument("--silver-warehouse", default=os.getenv("SODA_SILVER_WAREHOUSE", "s3://silver/warehouse"))
    ap.add_argument("--silver-namespace", default=os.getenv("SODA_SILVER_NAMESPACE", "silver"))
    ap.add_argument("--silver-parquet-root", default=os.getenv("SODA_SILVER_PARQUET_ROOT", "s3://silver/export"))
    ap.add_argument(
        "--gold-db", type=Path, default=Path(os.getenv("GOLD_DUCKDB_PATH", ROOT / "data" / "football.duckdb"))
    )
    ap.add_argument("--out", type=Path, default=Path(os.getenv("SODA_OUT_DIR", ROOT / "data" / "soda")))
    ap.add_argument(
        "--demo-failure",
        action="store_true",
        help="corrupt this run's view on purpose and succeed only if the checks catch it",
    )
    ap.add_argument(
        "--inject-damage",
        action="store_true",
        help="the damage of --demo-failure, reported like a real run (exit 1, <layer>-damaged.json)",
    )
    a = ap.parse_args()
    if (a.demo_failure or a.inject_damage) and a.layer == "all":
        ap.error("--demo-failure and --inject-damage need one layer: --layer silver or --layer gold")
    if a.demo_failure and a.inject_damage:
        ap.error("choose --demo-failure or --inject-damage")

    a.out.mkdir(parents=True, exist_ok=True)
    ok = True
    for layer in ("silver", "gold") if a.layer == "all" else (a.layer,):
        con = (
            silver_connection(a.silver_reader, a.silver_warehouse, a.silver_namespace, a.silver_parquet_root)
            if layer == "silver"
            else gold_connection(a.gold_db)
        )
        damage = corrupt(con, layer) if a.demo_failure or a.inject_damage else []
        for line in damage:
            print(f"DEMO: injected {line}")
        scan, summary = run_layer(layer, con, a.out)
        print(scan.get_logs_text())
        for c in summary["checks"]:
            if c["outcome"] in ("fail", "warn") and c["detail"]:
                print(f"WHY  {c['name']}\n     {c['detail']}")
        if a.demo_failure:
            caught = summary["failed"] > 0
            print(
                f"DEMO: {summary['failed']} check(s) failed on the corrupted data: "
                + ("the checks work." if caught else "NOTHING WAS CAUGHT, the checks are too weak.")
            )
            ok &= caught  # the demo result is not stored: it must not replace a real run
            continue
        # a damaged run never replaces the result of a real run, which the dashboard shows
        name = f"{layer}-damaged.json" if a.inject_damage else f"{layer}.json"
        (a.out / name).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        ok &= summary["failed"] == 0 and summary["errors"] == 0
        print(
            f"{layer}: {summary['passed']} passed, {summary['failed']} failed, {summary['warned']} warned, "
            f"{summary['errors']} errors"
        )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
