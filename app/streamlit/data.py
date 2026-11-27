"""data.py: how the dashboard reads the Gold tables, and the pieces every page shares.

Source (first one that applies):
  GOLD_PARQUET_DIR  a folder with <table>.parquet files (the export of `make gold`, copied locally)
  GOLD_DUCKDB_PATH  the DuckDB file written by dbt (default data/football.duckdb)
The DuckDB file is opened read-only for the time of one query and closed at once: DuckDB allows a single writer and
a connection that stays open would block the next `make gold`. Results are cached for a minute.
"""

import json
import os
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
GOLD_TABLES = (
    "gold_player_match_stats",
    "gold_team_match_stats",
    "gold_zone_occupancy",
    "gold_pass_network",
    "gold_shots",
    "gold_player_5min",
    "gold_match_library",
    "gold_player_card",
    "gold_player_fatigue",
    "gold_events",
    "gold_match_timeline",
    "gold_team_profile",
    "gold_team_shape",
    "gold_pressing",
    "gold_team_build_up",
    "gold_space_control",
)
CREDIT = "Data: SkillCorner open data (MIT licence). Real tracking data of A-League matches."
CAVEAT = (
    "Distances, speeds and sprints cover **tracked seconds only** (about 3/4 of each match) and come from 1 Hz "
    "positions: they are approximate and under-estimate real values. Compare players inside a match rather than "
    "quoting absolute numbers. Player ids are local to a match."
)


def duckdb_path() -> Path:
    return Path(os.getenv("GOLD_DUCKDB_PATH", ROOT / "data" / "football.duckdb"))


def parquet_dir() -> Path | None:
    value = os.getenv("GOLD_PARQUET_DIR")
    return Path(value) if value else None


def source_key() -> str:
    folder = parquet_dir()
    return f"parquet:{folder}" if folder else f"duckdb:{duckdb_path()}"


@st.cache_data(ttl=60, show_spinner=False)
def _load(name: str, key: str) -> pd.DataFrame:  # `key` only makes the cache depend on the source
    folder = parquet_dir()
    if folder:
        return duckdb.sql(f"select * from read_parquet('{folder / (name + '.parquet')}')").df()
    con = duckdb.connect(str(duckdb_path()), read_only=True)
    try:
        return con.sql(f"select * from {name}").df()
    finally:
        con.close()


@st.cache_data(ttl=600, show_spinner=False, max_entries=2)
def _replay(match_id: str, key: str) -> pd.DataFrame:
    folder = parquet_dir()
    query = "select * from {} where match_id = ? order by ts, object_id"
    if folder:
        return duckdb.execute(query.format(f"read_parquet('{folder / 'gold_replay_frames.parquet'}')"), [match_id]).df()
    con = duckdb.connect(str(duckdb_path()), read_only=True)
    try:
        return con.execute(query.format("gold_replay_frames"), [match_id]).df()
    finally:
        con.close()


def replay_frames(match_id: str) -> pd.DataFrame:
    """gold_replay_frames of one match (about 100,000 rows): the Replay page never loads every match at once."""
    return _replay(match_id, source_key())


def table(name: str) -> pd.DataFrame:
    """One Gold table as a DataFrame."""
    if name not in GOLD_TABLES:
        raise ValueError(f"unknown Gold table {name}")
    return _load(name, source_key())


def require_gold() -> pd.DataFrame:
    """Team table of every match, or a clear message and a stop if Gold is not there yet."""
    folder = parquet_dir()
    missing = (folder is not None and not (folder / "gold_team_match_stats.parquet").exists()) or (
        folder is None and not duckdb_path().exists()
    )
    if missing:
        st.error("The Gold tables are not available yet.")
        st.markdown(
            'Run the pipeline first: `make silver MATCH="m001 m002"`, then `make gold`. '
            f"The dashboard reads `{folder or duckdb_path()}`."
        )
        st.stop()
    try:
        teams = table("gold_team_match_stats")
    except duckdb.Error as exc:
        st.error("The Gold file exists but cannot be read: is `make gold` writing it right now? Try again in a moment.")
        st.caption(str(exc)[:300])
        st.stop()
    if teams.empty:
        st.warning("Gold is empty: run `make silver` then `make gold`.")
        st.stop()
    return teams


def match_label(teams: pd.DataFrame, match_id: str) -> str:
    rows = teams[teams.match_id == match_id].set_index("team_id")
    if "HOME" not in rows.index or "AWAY" not in rows.index:
        return match_id
    return (
        f"{match_id}: {rows.loc['HOME', 'team_short']} {rows.loc['HOME', 'score']}-{rows.loc['AWAY', 'score']} "
        f"{rows.loc['AWAY', 'team_short']}"
    )


def current_match(teams: pd.DataFrame) -> str:
    """The match chosen on Home or in the sidebar; it follows the visitor from page to page."""
    ids = sorted(teams.match_id.unique())
    chosen = st.session_state.get("match_id")
    return chosen if chosen in ids else ids[0]


def library() -> pd.DataFrame | None:
    """gold_match_library, newest match first; None if this Gold file predates it (run `make gold`)."""
    try:
        return table("gold_match_library").sort_values(["match_date", "match_id"], ascending=[False, True])
    except duckdb.Error:
        return None


def clock_bounds(match_id: str) -> tuple[int, int | None]:
    """(p1_start_ts, p2_start_ts) of a stored match for the football clock; (0, None) if the library predates them."""
    lib = library()
    if lib is None or "p2_start_ts" not in lib or match_id not in set(lib.match_id):
        return 0, None
    row = lib[lib.match_id == match_id].iloc[0]
    return int(row.p1_start_ts), int(row.p2_start_ts)


def fan_names(match_id: str) -> dict[str, str] | None:
    """{"HOME": "Brisbane Roar", "AWAY": ...}: the names fans use, for a match stored in Gold; None otherwise."""
    try:
        teams = table("gold_team_match_stats")
    except duckdb.Error:
        return None
    rows = teams[teams.match_id == match_id]
    return dict(zip(rows.team_id, rows.team_short, strict=True)) or None


def soda_results() -> dict[str, dict]:
    """Last Soda run per layer (data/soda/<layer>.json, written by `make soda`)."""
    folder = Path(os.getenv("SODA_OUT_DIR", ROOT / "data" / "soda"))
    out = {}
    for layer in ("silver", "gold"):
        path = folder / f"{layer}.json"
        if path.exists():
            out[layer] = json.loads(path.read_text(encoding="utf-8"))
    return out


def pipeline_file(name: str):
    """data/pipeline/<name>.json written by Dagster after each run (graph, runs); None before the first run."""
    path = Path(os.getenv("PIPELINE_OUT_DIR", ROOT / "data" / "pipeline")) / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


@st.cache_data(show_spinner=False)
def _manifest(path: str, _mtime: float) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dbt_manifest() -> dict | None:
    """dbt/target/manifest.json (written by every dbt command: `make gold`, Dagster); None if dbt never ran."""
    path = Path(os.getenv("DBT_MANIFEST", ROOT / "dbt" / "target" / "manifest.json"))
    return _manifest(str(path), path.stat().st_mtime) if path.exists() else None


def doc_text(doc: str) -> str:
    """The whole text of docs/<doc>."""
    return (ROOT / "docs" / doc).read_text(encoding="utf-8")


def doc_section(doc: str, heading: str) -> str:
    """The text of one `## heading` section of docs/<doc>, so a page and its document never disagree."""
    text = (ROOT / "docs" / doc).read_text(encoding="utf-8")
    start = text.index(f"## {heading}\n") + len(heading) + 4
    end = text.find("\n## ", start)
    return text[start : end if end >= 0 else None].strip()


def _yaml(path: Path):
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None


def dimension_map() -> dict:
    """soda/dimensions.yml: table -> check name -> {dimension, plain}."""
    return _yaml(ROOT / "soda" / "dimensions.yml") or {}


def external_checks() -> dict | None:
    """docs/external_checks.yml: what official sources say about goal minutes and possession."""
    return _yaml(ROOT / "docs" / "external_checks.yml")


def quality_evidence() -> dict | None:
    """docs/quality_evidence.yml, written by `make evidence`; None before its first run."""
    return _yaml(Path(os.getenv("QUALITY_EVIDENCE", ROOT / "docs" / "quality_evidence.yml")))


def silver_reports() -> dict[str, dict]:
    """data/quality/silver_<match>.json, written by the Silver job for each match it processes."""
    folder = Path(os.getenv("QUALITY_OUT_DIR", ROOT / "data" / "quality"))
    return (
        {
            p.stem.removeprefix("silver_"): json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(folder.glob("silver_*.json"))
        }
        if folder.exists()
        else {}
    )


def dbt_tests() -> tuple[int, int] | None:
    """(passed, total) dbt tests of the last dbt build (dbt/target/run_results.json)."""
    path = Path(os.getenv("DBT_RUN_RESULTS", ROOT / "dbt" / "target" / "run_results.json"))
    if not path.exists():
        return None
    tests = [r for r in json.loads(path.read_text(encoding="utf-8"))["results"] if r["unique_id"].startswith("test.")]
    return (sum(r["status"] == "pass" for r in tests), len(tests)) if tests else None


@st.cache_data(ttl=60, show_spinner=False)
def _replay_counts(key: str) -> pd.DataFrame:
    query = (
        "select match_id, count(*) filter (where object_type = 'player') as players, "
        "count(*) filter (where object_type = 'ball') as balls from {} group by 1"
    )
    folder = parquet_dir()
    if folder:
        return duckdb.sql(query.format(f"read_parquet('{folder / 'gold_replay_frames.parquet'}')")).df()
    con = duckdb.connect(str(duckdb_path()), read_only=True)
    try:
        return con.execute(query.format("gold_replay_frames")).df()
    finally:
        con.close()


def replay_counts() -> pd.DataFrame:
    """Player and ball rows of gold_replay_frames per match (Completeness: did Gold keep every Silver second?)."""
    return _replay_counts(source_key())
