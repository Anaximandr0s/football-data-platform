"""quality.py: the Data quality page in six dimensions (completeness, uniqueness, validity, consistency, accuracy,
freshness). Pure functions over what the pipeline leaves behind: the Soda results (data/soda), the dimension of each
check (soda/dimensions.yml), the Silver report of each match (data/quality), the Dagster runs (data/pipeline), Gold,
the external checks (docs/external_checks.yml) and the proofs of `make evidence` (docs/quality_evidence.yml)."""

from dataclasses import dataclass

import pandas as pd

import clock

DIMENSIONS = ("completeness", "uniqueness", "validity", "consistency", "accuracy", "freshness")
FRENCH = {
    "completeness": "Complétude",
    "uniqueness": "Unicité",
    "validity": "Validité",
    "consistency": "Cohérence",
    "accuracy": "Exactitude",
    "freshness": "Fraîcheur",
}
QUESTION = {
    "completeness": "Did we keep everything we received?",
    "uniqueness": "Is every row there only once?",
    "validity": "Are all values possible?",
    "consistency": "Do the tables agree with each other?",
    "accuracy": "Does it match the official match reports?",
    "freshness": "How recent is the data?",
}
GREEN, ORANGE, RED, GREY = "green", "orange", "red", "grey"
FRESH_S = 600  # Gold rebuilt within 10 minutes of the final whistle


@dataclass(frozen=True)
class Card:
    dimension: str
    status: str
    number: str  # the big number
    lines: list  # what it is made of, in plain words


# ---------------------------------------------------------------- the Soda checks, by dimension


def checks_table(results: dict, mapping: dict) -> pd.DataFrame:
    """Every check of the last run: plain name, dimension, layer, table, result (pass / fail / ...)."""
    rows = []
    for layer, summary in results.items():
        for c in summary["checks"]:
            entry = mapping.get(c["table"], {}).get(c["name"], {})
            rows.append(
                {
                    "check": entry.get("plain", c["name"]),
                    "dimension": entry.get("dimension", "unmapped"),
                    "layer": layer,
                    "table": c["table"],
                    "result": c["outcome"],
                    "detail": c.get("detail") or "",
                }
            )
    return pd.DataFrame(rows, columns=["check", "dimension", "layer", "table", "result", "detail"])


def failed(checks: pd.DataFrame, dimension: str | None = None) -> pd.DataFrame:
    rows = checks[~checks.result.isin(["pass", "warn"])]
    return rows if dimension is None else rows[rows.dimension == dimension]


def verdict(checks: pd.DataFrame, last_check: str | None, matches: int) -> tuple[str, str]:
    """(status, sentence) of the banner."""
    total, bad = len(checks), failed(checks)
    when = f"last check {last_check}" if last_check else "no check run yet"
    if total == 0:
        return GREY, "No quality check has run yet: run `make soda`."
    if bad.empty:
        return GREEN, f"The data is ready to use · {total} of {total} checks passed · {when} · {matches} matches"
    dims = ", ".join(sorted(set(bad.dimension)))
    return RED, (
        f"{len(bad)} of {total} checks failed ({dims}): the numbers they cover should not be trusted until "
        f"fixed · {when} · {matches} matches"
    )


# ---------------------------------------------------------------- per match measures


def kept(reports: dict, frames: pd.DataFrame) -> pd.DataFrame:
    """Per match: rows prepared from the source, kept in Silver, and Silver tracking + ball rows found in Gold's replay
    frames. reports: match_id -> data/quality/silver_<match>.json; frames: match_id, players, balls (Gold counts)."""
    rows = []
    for match_id, r in sorted(reports.items()):
        prepared = sum((r.get("prepared_rows") or {}).values())
        silver = sum(r["silver_rows"].values())
        g = frames[frames.match_id == match_id]
        gold = int(g.players.sum() + g.balls.sum()) if not g.empty else 0
        expected_gold = r["silver_rows"]["tracking"] + r["silver_rows"]["ball"]
        rows.append(
            {
                "match_id": match_id,
                "prepared": prepared,
                "silver": silver,
                "gold": gold,
                "gold_expected": expected_gold,
                "kept_share": min(silver / prepared if prepared else 0, gold / expected_gold if expected_gold else 0),
                # reports written before Silver read one replay call it replay_copies_removed
                "copies_removed": sum((r.get("duplicates_removed") or r.get("replay_copies_removed")).values()),
                "replays_in_bronze": r.get("replays_in_bronze"),
                "positions_corrected": r["positions_corrected"],
                "speeds_rejected": r["speeds_rejected"],
                "tracking_rows": r["tracking_rows"],
            }
        )
    return pd.DataFrame(rows)


def accuracy(external: dict, events: pd.DataFrame, library: pd.DataFrame, profile: pd.DataFrame) -> pd.DataFrame:
    """One row per goal and one per possession: ours (from Gold), the sources, and the verdict (exact / 1 min /
    off; within 1 / 2 points / off). A goal is matched by its rank in its match; its scorer must agree."""
    names = {k: v["name"] for k, v in external["sources"].items()}
    rows = []
    for match_id, m in external["matches"].items():
        lib = library[library.match_id == match_id]
        if lib.empty:
            continue
        p1, p2 = int(lib.p1_start_ts.iloc[0]), int(lib.p2_start_ts.iloc[0])
        goals = events[(events.match_id == match_id) & (events.type == "goal")].sort_values("ts")
        for g, (_, row) in zip(m["goals"], goals.iterrows(), strict=False):
            ours = clock.minute(int(row.ts), int(row.period), p1, p2)
            minute = ours[0] + ours[1]
            gap = min(abs(minute - v) for v in g["sources"].values())
            rows.append(
                {
                    "match_id": match_id,
                    "what": f"goal {g['scorer']}",
                    "ours": f"{clock.label(row.ts, row.period, p1, p2)}",
                    "sources": ", ".join(f"{names[s]} {v}'" for s, v in g["sources"].items()),
                    "status": GREEN if gap == 0 else ORANGE if gap <= 1 else RED,
                    "scorer_agrees": g["scorer"].split()[-1] in str(row.player_short_name),
                }
            )
        home = profile[(profile.match_id == match_id) & (profile.team_id == "HOME")]
        if not home.empty and "possession" in m:
            ours = float(home.possession_share.iloc[0])
            gap = min(abs(ours - v) for v in m["possession"]["sources"].values()) * 100
            rows.append(
                {
                    "match_id": match_id,
                    "what": "possession (HOME)",
                    "ours": f"{ours:.1%}",
                    "sources": ", ".join(f"{names[s]} {v:.0%}" for s, v in m["possession"]["sources"].items()),
                    "status": GREEN if gap <= 1 + 1e-9 else ORANGE if gap <= 2 + 1e-9 else RED,
                    "scorer_agrees": True,
                }
            )
    return pd.DataFrame(rows, columns=["match_id", "what", "ours", "sources", "status", "scorer_agrees"])


def freshness(runs: list[dict], match_id: str) -> tuple[str, float | None, str | None]:
    """(status, seconds from the final whistle to Gold ready, replay) for the match's latest replay. The final whistle is
    taken as the start of the run the sensor launched (it reads Kafka every 15 s); Gold is ready at the end of the first
    successful `gold` step that started after it, whatever match triggered that step."""
    mine = [r for r in runs if r.get("match_id") == match_id and r.get("replay_id")]
    if not mine:
        return GREY, None, None
    latest = max(mine, key=lambda r: r["replay_id"])
    whistle = latest["started"]
    ready = [
        s["end"]
        for r in runs
        for s in r.get("steps", [])
        if s["step"] == "gold" and s["status"] == "SUCCESS" and s.get("start") and s["start"] >= whistle
    ]
    if not ready:
        return RED, None, latest["replay_id"]
    seconds = min(ready) - whistle
    return (GREEN if seconds <= FRESH_S else ORANGE), seconds, latest["replay_id"]


def grid(
    matches: list[str], checks: pd.DataFrame, kept_rows: pd.DataFrame, acc: pd.DataFrame, runs: list[dict]
) -> pd.DataFrame:
    """Match x dimension status. Completeness judges our pipeline (what we kept), never the camera."""
    worst = {GREEN: 0, ORANGE: 1, RED: 2, GREY: -1}
    out = []
    for m in matches:
        k = kept_rows[kept_rows.match_id == m]
        row = {"match_id": m}
        complete = not k.empty and float(k.kept_share.iloc[0]) >= 1.0
        row["completeness"] = RED if failed(checks, "completeness").shape[0] or not complete else GREEN
        row["uniqueness"] = RED if failed(checks, "uniqueness").shape[0] else GREEN
        fixed = not k.empty and (int(k.positions_corrected.iloc[0]) or int(k.speeds_rejected.iloc[0]))
        row["validity"] = RED if failed(checks, "validity").shape[0] else ORANGE if fixed else GREEN
        row["consistency"] = RED if failed(checks, "consistency").shape[0] else GREEN
        a = acc[acc.match_id == m]
        row["accuracy"] = GREY if a.empty else max(a.status, key=worst.get)
        if failed(checks, "accuracy").shape[0]:
            row["accuracy"] = RED
        row["freshness"] = freshness(runs, m)[0]
        out.append(row)
    return pd.DataFrame(out, columns=["match_id", *DIMENSIONS])


def caught(runs: list[dict], evidence: dict) -> list[dict]:
    """The failures our checks stopped: from the Dagster runs, explained by `make evidence` (the fix and its commit)."""
    known = {c["run_id"][:8]: c for c in (evidence or {}).get("caught", [])}
    out = []
    for r in runs:
        if r["status"] != "FAILURE":
            continue
        e = known.get(r["run_id"][:8], {})
        out.append(
            {
                "run": r["run_id"][:8],
                "match_id": r.get("match_id"),
                "when": r.get("started"),
                "stopped_at": ", ".join(s["step"] for s in r.get("steps", []) if s["status"] == "FAILURE"),
                "not_built": ", ".join(s["step"] for s in r.get("steps", []) if s["status"] == "SKIPPED"),
                "what": e.get("what", "not explained yet"),
                "fix": e.get("fix_commit"),
            }
        )
    for e in (evidence or {}).get("caught", []):  # explained failures older than the runs kept in runs.json
        if e["run_id"][:8] not in {o["run"] for o in out}:
            out.append(
                {
                    "run": e["run_id"][:8],
                    "match_id": e.get("match_id"),
                    "when": None,
                    "stopped_at": e.get("step"),
                    "not_built": e.get("not_built", ""),
                    "what": e["what"],
                    "fix": e.get("fix_commit"),
                }
            )
    return out


# ---------------------------------------------------------------- the six cards


def _status(checks: pd.DataFrame, dimension: str) -> str:
    return RED if not failed(checks, dimension).empty else GREEN


def _count(checks: pd.DataFrame, dimension: str) -> str:
    d = checks[checks.dimension == dimension]
    return f"{len(d) - len(failed(checks, dimension))} of {len(d)} checks passed"


def cards(
    checks: pd.DataFrame,
    kept_rows: pd.DataFrame,
    library: pd.DataFrame,
    acc: pd.DataFrame,
    runs: list[dict],
    dbt_tests: tuple[int, int] | None,
    evidence: dict | None,
    last_check: str | None,
) -> list[Card]:
    ev = evidence or {}
    out = []
    prepared, silver = int(kept_rows.prepared.sum()), int(kept_rows.silver.sum())
    gold_ok = bool((kept_rows.gold == kept_rows.gold_expected).all()) if not kept_rows.empty else False
    share = min(silver / prepared, 1.0 if gold_ok else 0.0) if prepared else 0.0
    seen = float(library.tracked_share.mean()) if not library.empty else 0.0
    status = RED if _status(checks, "completeness") == RED or share < 1 else GREEN
    out.append(
        Card(
            "completeness",
            status,
            f"{share:.0%}" if prepared else "–",
            [
                f"{silver:,} of the {prepared:,} rows we received are in Silver, and Gold's replay holds every one of them"
                if gold_ok
                else f"{silver:,} of the {prepared:,} rows we received are in Silver; Gold's replay is missing some",
                f"the camera saw {seen:.0%} of the match time (a limit of the source, not of our pipeline)",
                _count(checks, "completeness") + " (no empty table, no missing key, 22 players in every second seen)",
            ],
        )
    )
    copies = int(kept_rows.copies_removed.sum()) if not kept_rows.empty else 0
    replays = int(kept_rows.replays_in_bronze.fillna(0).sum()) if not kept_rows.empty else 0
    dupes = len(failed(checks, "uniqueness"))
    out.append(
        Card(
            "uniqueness",
            _status(checks, "uniqueness"),
            f"{dupes}" if dupes else "0 duplicates",
            [
                (
                    f"Silver read one replay per match, the latest complete one, of {replays:,} kept in Bronze; it removed "
                    f"{copies:,} rows delivered twice"
                    if replays
                    else f"{copies:,} copies from replaying the matches were removed by Silver"
                ),
                _count(checks, "uniqueness") + " (one row per key in every table)",
            ],
        )
    )
    corrected = int(kept_rows.positions_corrected.sum()) if not kept_rows.empty else 0
    rows = int(kept_rows.tracking_rows.sum()) if not kept_rows.empty else 0
    rejected = int(library.speeds_rejected.sum()) if "speeds_rejected" in library else 0
    out.append(
        Card(
            "validity",
            _status(checks, "validity"),
            "0 impossible values"
            if _status(checks, "validity") == GREEN
            else f"{len(failed(checks, 'validity'))} failed",
            [
                f"{corrected:,} positions slightly off the pitch were put back on its edge ({corrected / rows:.1%} of positions)"
                if rows
                else "positions: no Silver report yet",
                f"{rejected} impossible speeds (above 40 km/h) were removed",
                _count(checks, "validity") + " (allowed values: event types, teams, periods, pitch size)",
            ],
        )
    )
    lines = [_count(checks, "consistency") + " (totals add up, the score is the same in every table)"]
    if dbt_tests:
        lines.append(f"{dbt_tests[0]} of {dbt_tests[1]} dbt tests passed (Gold against Silver)")
    for key, text in (("live_equals_gold", "Live = Gold"), ("streaming_equals_gold", "Streaming = Gold")):
        e = ev.get(key)
        if e:
            lines.append(f"{text}: {e['summary']} ({e['date']})")
    out.append(
        Card("consistency", _status(checks, "consistency"), _count(checks, "consistency").split(" checks")[0], lines)
    )
    goals = acc[acc.what.str.startswith("goal")]
    poss = acc[acc.what.str.startswith("possession")]
    exact, close = int((goals.status == GREEN).sum()), int((goals.status != RED).sum())
    status = (
        RED
        if (not goals.empty and close < len(goals)) or _status(checks, "accuracy") == RED
        else ORANGE
        if (exact < len(goals) or (poss.status != GREEN).any())
        else GREEN
    )
    out.append(
        Card(
            "accuracy",
            status if not acc.empty else GREY,
            f"{exact} of {len(goals)}" if not goals.empty else "–",
            [
                f"goal minutes the same as at least one official report; {close} of {len(goals)} within 1 minute",
                f"possession within 1 point of a source in {int((poss.status == GREEN).sum())} of {len(poss)} matches"
                + (
                    f", within 2 in the other{'s' if (poss.status != GREEN).sum() > 1 else ''}"
                    if (poss.status == ORANGE).any()
                    else ""
                ),
                "the goals in our data equal the real final score"
                + ("" if _status(checks, "accuracy") == GREEN else ": NO"),
            ],
        )
    )
    times = [freshness(runs, m)[1] for m in sorted({r.get("match_id") for r in runs if r.get("replay_id")})]
    times = [t for t in times if t is not None]
    statuses = [freshness(runs, m)[0] for m in sorted({r.get("match_id") for r in runs if r.get("replay_id")})]
    status = GREY if not statuses else RED if RED in statuses else ORANGE if ORANGE in statuses else GREEN
    delay = ev.get("live_delay")
    out.append(
        Card(
            "freshness",
            status,
            f"{pd.Series(times).median() / 60:.1f} min" if times else "–",
            [
                "median time from the final whistle of a replay to Gold ready (Dagster)",
                f"last quality check {last_check}" if last_check else "no quality check yet",
                f"live: {delay['summary']} ({delay['date']})"
                if delay
                else "live delay: not measured yet (`make evidence`)",
            ],
        )
    )
    return out
