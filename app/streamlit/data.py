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
GOLD_TABLES = ("gold_player_match_stats", "gold_team_match_stats", "gold_zone_occupancy",
               "gold_pass_network", "gold_shots", "gold_player_5min", "gold_match_library", "gold_player_card",
               "gold_player_fatigue", "gold_events", "gold_match_timeline", "gold_team_profile")
CREDIT = "Data: SkillCorner open data (MIT licence). Real tracking data of A-League matches."
CAVEAT = ("Distances, speeds and sprints cover **tracked seconds only** (about 3/4 of each match) and come from 1 Hz "
          "positions: they are approximate and under-estimate real values. Compare players inside a match rather than "
          "quoting absolute numbers. Player ids are local to a match.")


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


def table(name: str) -> pd.DataFrame:
    """One Gold table as a DataFrame."""
    if name not in GOLD_TABLES:
        raise ValueError(f"unknown Gold table {name}")
    return _load(name, source_key())


def require_gold() -> pd.DataFrame:
    """Team table of every match, or a clear message and a stop if Gold is not there yet."""
    folder = parquet_dir()
    missing = (folder is not None and not (folder / "gold_team_match_stats.parquet").exists()) or \
              (folder is None and not duckdb_path().exists())
    if missing:
        st.error("The Gold tables are not available yet.")
        st.markdown("Run the pipeline first: `make silver MATCH=\"m001 m002\"`, then `make gold`. "
                    f"The dashboard reads `{folder or duckdb_path()}`.")
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
    return f"{match_id}: {rows.loc['HOME', 'team_short']} {rows.loc['HOME', 'score']}-{rows.loc['AWAY', 'score']} " \
           f"{rows.loc['AWAY', 'team_short']}"


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


def mmss(ts: int) -> str:
    return f"{int(ts) // 60:02d}:{int(ts) % 60:02d}"


def soda_results() -> dict[str, dict]:
    """Last Soda run per layer (data/soda/<layer>.json, written by `make soda`)."""
    folder = Path(os.getenv("SODA_OUT_DIR", ROOT / "data" / "soda"))
    out = {}
    for layer in ("silver", "gold"):
        path = folder / f"{layer}.json"
        if path.exists():
            out[layer] = json.loads(path.read_text(encoding="utf-8"))
    return out
