"""The chain of one match: bronze -> silver -> Soda Silver -> Gold (dbt) -> Soda Gold -> post-match report.

Every step runs the project's own command (check_bronze, the Silver Spark job, dbt, soda/run_checks.py), so a Dagster run
does exactly what `make check / silver / gold / soda` does. All steps are partitioned by match_id; Gold is rebuilt whole
(one DuckDB file holds every match), so its partition only says which match triggered it. The steps that open the DuckDB
file share the pool `duckdb` (limit 1, dagster.yaml): two matches ending together queue there instead of colliding.
"""
import json
import os
import socket
import subprocess
import time
from pathlib import Path

import dagster as dg
from dagster_dbt import DagsterDbtTranslator, DbtCliResource, dbt_assets

from football_platform import soda

ROOT = Path(__file__).resolve().parents[2]
DBT_DIR = ROOT / "dbt"
MANIFEST = Path(os.getenv("DBT_MANIFEST", DBT_DIR / "target" / "manifest.json"))
SODA_OUT = Path(os.getenv("SODA_OUT_DIR", ROOT / "data" / "soda"))
REPORTS = Path(os.getenv("PIPELINE_OUT_DIR", ROOT / "data" / "pipeline")) / "reports"
GOLD_DB = Path(os.getenv("GOLD_DUCKDB_PATH", ROOT / "data" / "football.duckdb"))
BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
BRONZE_WAIT_S = int(os.getenv("BRONZE_WAIT_S", "180"))
SPARK_PACKAGES = os.getenv("SPARK_JARS_PACKAGES", "org.apache.hadoop:hadoop-aws:3.4.1,"
                                                  "org.apache.iceberg:iceberg-spark-runtime-4.0_2.13:1.10.0")
DUCKDB_POOL = "duckdb"
RETRY = dg.RetryPolicy(max_retries=2, delay=30)

matches = dg.DynamicPartitionsDefinition(name="match_id")
damage_config = {"inject_damage": dg.Field(bool, default_value=False,
                                           description="damage this check's view of the data on purpose (demo)")}


def run(context, args: list[str], ok_codes: tuple[int, ...] = (0,)) -> str:
    """Run a project command from the repository root; its output goes to the Dagster log."""
    context.log.info("$ " + " ".join(args))
    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                          env={**os.environ, "PYTHONPATH": str(ROOT)})
    # stdout is the command's own report (checks, counts); stderr is Spark's or dbt's log: keep the report whole
    context.log.info(proc.stdout[-20000:])
    if proc.stderr:
        context.log.debug(proc.stderr[-6000:])
    if proc.returncode not in ok_codes:
        raise dg.Failure(f"{args[0]} exited with {proc.returncode}",
                         metadata={"report": dg.MetadataValue.text(proc.stdout[-6000:]),
                                   "log": dg.MetadataValue.text(proc.stderr[-3000:])})
    return proc.stdout


def wait_until(check, deadline_s: float, every_s: float = 10, clock=time.time, sleep=time.sleep):
    """Calls check() -> (done, report) until done or deadline_s have passed. Returns (done, last report)."""
    end = clock() + deadline_s
    while True:
        done, report = check()
        if done or clock() >= end:
            return done, report
        sleep(every_s)


def check_bronze(context) -> tuple[bool, str]:
    """One run of ingestion.check_bronze for the run's replay: done when no table is MISSING (exit code 0)."""
    args = ["python", "-m", "ingestion.check_bronze", "--match", context.partition_key, *replay_args(context)]
    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(ROOT)})
    if proc.returncode not in (0, 1):               # 1 = rows still missing; anything else is a crash: say it
        raise dg.Failure(f"check_bronze exited with {proc.returncode}", metadata={
            "log": dg.MetadataValue.text((proc.stdout + proc.stderr)[-3000:])})
    return proc.returncode == 0, proc.stdout


def replay_args(context) -> list[str]:
    """The replay the run is about (tag replay_id, set by the sensor and the benchmark rebuild): Bronze is checked and
    Silver built from that replay only. A run without it uses the newest (check) / latest complete (Silver) one."""
    replay = context.run.tags.get("replay_id")
    return ["--replay", replay] if replay else []


@dg.asset(partitions_def=matches, group_name="bronze", kinds={"kafka", "s3"})
def bronze(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    """Every message of this replay is in Bronze: its folder holds at least the rows of the prepared files
    (python -m ingestion.check_bronze --replay). Only this replay counts: other replays still streaming, and the
    Bronze writer's total lag, do not hold it back."""
    def check():
        done, report = check_bronze(context)
        if not done:
            context.log.info("waiting for this replay's rows in Bronze:\n" + report.strip())
        return done, report

    done, report = wait_until(check, BRONZE_WAIT_S)
    if not done:
        raise dg.Failure(f"rows of this replay are still missing in Bronze after {BRONZE_WAIT_S} s: is the Bronze "
                         "writer running?", metadata={"check_bronze": dg.MetadataValue.md(f"```\n{report.strip()}\n```")})
    return dg.MaterializeResult(metadata={"check_bronze": dg.MetadataValue.md(f"```\n{report.strip()}\n```")})


@dg.asset(partitions_def=matches, deps=[bronze], group_name="silver", kinds={"spark", "iceberg"}, retry_policy=RETRY)
def silver(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    """Bronze -> Silver for one match on the Spark cluster (spark/silver/bronze_to_silver.py). The driver runs in this
    container: spark.driver.host is the name the workers use to reach it."""
    out = run(context, [
        "spark-submit", "--master", os.getenv("SPARK_MASTER", "spark://spark-master:7077"),
        "--packages", SPARK_PACKAGES, "--conf", "spark.jars.ivy=/tmp/ivy",
        "--conf", f"spark.driver.host={os.getenv('SPARK_DRIVER_HOST', socket.gethostname())}",
        "--conf", "spark.driver.bindAddress=0.0.0.0", "--driver-memory", "1g", "--executor-memory", "1g",
        # one core each: two matches build Silver side by side, and the streaming job keeps its core
        "--conf", "spark.cores.max=1",
        str(ROOT / "spark" / "silver" / "bronze_to_silver.py"), "--packages", "", "--match", context.partition_key,
        *replay_args(context)])
    return dg.MaterializeResult(metadata={"silver report": dg.MetadataValue.text(out[-4000:])})


def soda_run(context, layer: str, inject_damage: bool) -> dict:
    """soda/run_checks.py for one layer; returns its result file. Exit code 1 = a check failed: the result says which."""
    args = ["python", "soda/run_checks.py", "--layer", layer, "--out", str(SODA_OUT)]
    run(context, args + (["--inject-damage"] if inject_damage else []), ok_codes=(0, 1))
    name = f"{layer}-damaged.json" if inject_damage else f"{layer}.json"
    return json.loads((SODA_OUT / name).read_text(encoding="utf-8"))


def soda_metadata(summary: dict, table: str | None = None) -> dict:
    failed = soda.failed_checks(summary, table)
    return {"passed": summary["passed"], "failed": summary["failed"], "errors": summary["errors"],
            "failed checks": dg.MetadataValue.md("\n".join(f"- {n}" for n in failed) or "none")}


@dg.asset_check(asset=silver, blocking=True, config_schema=damage_config)
def soda_silver(context: dg.AssetCheckExecutionContext) -> dg.AssetCheckResult:
    """The 73 Soda checks on the Silver tables (soda/checks/silver.yml). Blocking: Gold is not rebuilt if one fails."""
    summary = soda_run(context, "silver", context.op_execution_context.op_config["inject_damage"])
    return dg.AssetCheckResult(passed=soda.passed(summary), metadata=soda_metadata(summary))


class Translator(DagsterDbtTranslator):
    """dbt models keep their names as asset keys; the staging models read Silver (through a macro, not a dbt source),
    so the dependency is declared here."""

    def get_asset_spec(self, manifest, unique_id, project):
        spec = super().get_asset_spec(manifest, unique_id, project).replace_attributes(group_name="gold")
        if unique_id.split(".")[-1].startswith("stg_"):
            spec = spec.merge_attributes(deps=[dg.AssetDep(silver.key)])
        return spec


@dbt_assets(manifest=MANIFEST, partitions_def=matches, dagster_dbt_translator=Translator(), retry_policy=RETRY,
            pool=DUCKDB_POOL)
def gold(context: dg.AssetExecutionContext, dbt: DbtCliResource):
    """dbt build of every model and test, then the export to s3://gold (make gold)."""
    yield from dbt.cli(["build", "--vars", '{"export_gold": true}'], context=context).stream()


GOLD_TABLES = sorted(k for k in gold.keys if k.path[-1].startswith("gold_"))


@dg.multi_asset_check(specs=[dg.AssetCheckSpec("soda_gold", asset=k, blocking=True) for k in GOLD_TABLES],
                      config_schema=damage_config, pool=DUCKDB_POOL)
def soda_gold(context: dg.AssetCheckExecutionContext):
    """The Soda checks of each Gold table (soda/checks/gold.yml), one result per table. Blocking: no report if one fails."""
    summary = soda_run(context, "gold", context.op_execution_context.op_config["inject_damage"])
    for key in GOLD_TABLES:
        table = key.path[-1]
        yield dg.AssetCheckResult(asset_key=key, check_name="soda_gold", passed=soda.passed(summary, table),
                                  metadata=soda_metadata(summary, table))


@dg.asset(partitions_def=matches, deps=GOLD_TABLES, group_name="report", kinds={"duckdb"}, pool=DUCKDB_POOL)
def match_report(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    """Post-match report: the match as Gold tells it (score, coverage, team totals), in data/pipeline/reports/<id>.json."""
    import duckdb

    match_id = context.partition_key
    with duckdb.connect(str(GOLD_DB), read_only=True) as con:
        library = con.execute("select * from gold_match_library where match_id = ?", [match_id]).df()
        teams = con.execute("select team_id, team_short, score, distance_km, passes, shots, goals "
                            "from gold_team_match_stats where match_id = ? order by team_id desc", [match_id]).df()
    if library.empty:
        raise dg.Failure(f"{match_id} is not in Gold")
    m = library.iloc[0]
    report = {"match_id": match_id, "home": m.home_team_short, "away": m.away_team_short,
              "score": f"{m.home_score}-{m.away_score}", "tracked_share": float(m.tracked_share),
              "teams": json.loads(teams.to_json(orient="records")), "run_id": context.run.run_id,
              "replay_id": context.run.tags.get("replay_id")}
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"{match_id}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return dg.MaterializeResult(metadata={"score": report["score"], "tracked share": report["tracked_share"]})
