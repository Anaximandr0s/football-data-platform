"""quality_evidence.py (`make evidence`): re-run the comparisons the Data quality page quotes and write them, with the
date and the commit, to docs/quality_evidence.yml.

  live_equals_gold       every match's prepared rows (what the producer sends) through Live's own code (live.py):
                         each player's distance, sprints and top speed at full time against Gold, and the positions
                         of sample seconds against gold_replay_frames
  streaming_equals_gold  foot-live-stats (Spark Structured Streaming): the complete windows of each match's latest
                         replay against gold_match_timeline, gold_player_5min and gold_pressing
  live_delay             a 20 s replay of m002 at x1: time from sending a message to a consumer receiving it
  caught                 the failed Dagster runs (full history) and what each one stopped, with the commit of the fix

Needs the stack (Kafka, Dagster), the Gold file and data/prepared. The replay of live_delay adds 20 s of m002 to
Kafka and bronze (Silver removes the copies). Run from the repository root.
"""

import json
import logging
import os
import random
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import yaml
from confluent_kafka import Consumer, TopicPartition

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "app" / "streamlit")]
import live  # noqa: E402
from ingestion.producer_foot import read_records  # noqa: E402

log = logging.getLogger("evidence")
BOOTSTRAP = os.getenv("KAFKA_EXTERNAL_BOOTSTRAP", "localhost:29092")
DAGSTER = os.getenv("DAGSTER_GRAPHQL", "http://localhost:3000/graphql")
GOLD = Path(os.getenv("GOLD_DUCKDB_PATH", ROOT / "data" / "football.duckdb"))
OUT = ROOT / "docs" / "quality_evidence.yml"
SAMPLE_SECONDS = 8  # per match, half in each period
# what each failed run stopped, and the commit that fixed its cause (a run on purpose has no fix)
FIXES = {
    "a4ef3d8a": {
        "what": "The Soda Silver check could not read its own settings (a bug in our Dagster code). The check "
        "failed, so Gold was not rebuilt from a Silver nobody had checked.",
        "fix_commit": "0d3c37a",
        "fix": "read the check settings through the op context",
    },
    "ab6adb0d": {
        "what": "Damaged data on purpose: a duplicated row, a position off the pitch and a speed of 61 km/h. "
        "6 Silver checks failed and Gold was not updated (same file date and size before and after).",
        "fix_commit": None,
        "fix": "nothing to fix: a demonstration",
    },
    "18bf663e": {
        "what": "Silver refused m003 after its third replay: the speed gate counted every replayed copy of a "
        "rejected speed (12 instead of 4). Silver was not written, so Gold kept the previous data.",
        "fix_commit": "a654aea",
        "fix": "count the rejected speeds once per key",
    },
}


def gold() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(GOLD), read_only=True)


def live_equals_gold() -> dict:
    con = gold()
    players, positions, worst_m, worst_pos = 0, 0, 0.0, 0.0
    different = []
    for mdir in sorted((ROOT / "data" / "prepared").iterdir()):
        m = mdir.name
        if not con.execute("select count(*) from gold_match_library where match_id = ?", [m]).fetchone()[0]:
            continue
        info = read_records(mdir / "matches.parquet")[0]
        tracking = read_records(mdir / "tracking.parquet")
        state = live.apply(live.MatchState(m), "matches", info, 0)
        for rec in read_records(mdir / "players.parquet"):
            state = live.apply(state, "players", rec, 0)
        for i, rec in enumerate(tracking):
            state = live.apply(state, "tracking", rec, i)
        g = {
            r[0]: r[1:]
            for r in con.execute(
                "select s.player_id, s.distance_m, s.sprint_count, c.top_speed_kmh from gold_player_match_stats s "
                "join gold_player_card c using (match_id, player_id) where s.match_id = ?",
                [m],
            ).fetchall()
        }
        for pid, (distance, sprints, top) in g.items():
            st = live.player_stats(state, pid)
            players += 1
            # Gold rounds the distance and the top speed to 1 decimal: compare Live unrounded, within that rounding
            gap = abs(st.distance_m - distance)
            worst_m = max(worst_m, gap)
            top_gap = 0.0 if top is None or st.top_speed_kmh is None else abs(st.top_speed_kmh - top)
            if (
                st.sprint_count != sprints
                or (st.top_speed_kmh is None) != (top is None)
                or top_gap > 0.05 + 1e-6
                or gap > 0.05 + 1e-6
            ):
                different.append(f"{m} {pid}")
        by_ts = {}
        for rec in tracking:
            by_ts.setdefault(rec["ts"], []).append(rec)
        p2 = info["p2_start_ts"]
        random.seed(m)
        seconds = sorted(
            random.sample([t for t in by_ts if t < p2], SAMPLE_SECONDS // 2)
            + random.sample([t for t in by_ts if t >= p2], SAMPLE_SECONDS // 2)
        )
        for ts in seconds:
            one = live.apply(live.MatchState(m), "matches", info, 0)
            for rec in by_ts[ts]:
                one = live.apply(one, "tracking", rec, 1)
            _, _, drawn = live.silver_frame(one)
            ref = {
                o: (x, y)
                for o, x, y in con.execute(
                    "select object_id, x, y from gold_replay_frames where match_id = ? and ts = ? and object_type = 'player'",
                    [m, int(ts)],
                ).fetchall()
            }
            for pid, (x, y, _) in drawn.items():
                positions += 1
                worst_pos = max(worst_pos, abs(x - ref[pid][0]), abs(y - ref[pid][1]))
        log.info("live = gold: %s done", m)
    ok = not different and worst_pos == 0
    return {
        "ok": ok,
        "players": players,
        "positions": positions,
        "different": different,
        "largest_distance_gap_m": round(worst_m, 3),
        "largest_position_gap_m": worst_pos,
        "summary": (
            f"{players} players' distance, sprints and top speed, and {positions} positions, equal"
            if ok
            else f"{len(different)} players differ"
        ),
    }


def latest_rows() -> dict:
    c = Consumer(
        {
            "bootstrap.servers": BOOTSTRAP,
            "group.id": "evidence",
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
            "log_level": 3,
        }
    )
    tp = TopicPartition("foot-live-stats", 0)
    lo, hi = c.get_watermark_offsets(tp, timeout=10)
    c.assign([TopicPartition("foot-live-stats", 0, lo)])
    rows = {}
    while lo < hi:
        msgs = c.consume(5000, 3.0)
        for msg in msgs:
            rows[msg.key().decode()] = json.loads(msg.value())
        if not msgs or msgs[-1].offset() >= hi - 1:
            break
    c.close()
    return rows


def streaming_equals_gold() -> dict:
    con = gold()
    rows = latest_rows()
    gold_tables = {
        "team": (
            "gold_match_timeline",
            ["team_id", "window_index"],
            ["possession_seconds", "known_seconds", "possession_share", "passes", "defensive_actions"],
        ),
        "player": (
            "gold_player_5min",
            ["player_id", "window_index"],
            ["tracked_seconds", "coverage", "distance_m", "sprint_seconds", "max_speed_kmh"],
        ),
        "pressing": (
            "gold_pressing",
            ["team_id", "window_index"],
            ["defensive_actions", "opponent_passes", "ppp", "defensive_actions_final_third"],
        ),
    }
    per_match, different, ties, values = {}, [], 0, 0
    replays = {}
    for r in rows.values():
        if r["complete"]:
            replays.setdefault(r["match_id"], set()).add(r["replay_id"])
    for m, ids in sorted(replays.items()):
        # the latest replay whose rows are all complete (a replay stopped early is not a match)
        for replay in sorted(ids, reverse=True):
            mine = [r for r in rows.values() if r["replay_id"] == replay]
            if mine and all(r["complete"] for r in mine) and len(mine) > 400:
                break
        else:
            continue
        windows = 0
        for kind, (table, keys, cols) in gold_tables.items():
            g = con.execute(f"select * from {table} where match_id = ?", [m]).df().set_index(keys)
            for r in (x for x in mine if x["kind"] == kind):
                k = tuple(r[c] for c in keys)
                if k not in g.index:
                    different.append(f"{replay} {kind} {k} not in Gold")
                    continue
                windows += 1
                for col in cols:
                    want, got = g.loc[k][col], r[col]
                    values += 1
                    if want is None or got is None or want != want:
                        if (want is None or want != want) != (got is None):
                            different.append(f"{replay} {kind} {k} {col}")
                        continue
                    if abs(float(got) - float(want)) <= 1e-6:
                        continue
                    if col == "distance_m" and abs(float(got) - float(want)) <= 0.1 + 1e-9:
                        ties += 1  # the same sum, rounded apart by Spark and DuckDB on an exact .x5
                        continue
                    different.append(f"{replay} {kind} {k} {col}: {got} vs {want}")
        per_match[m] = {"replay": replay, "windows": windows}
    ok = not different and bool(per_match)
    return {
        "ok": ok,
        "matches": per_match,
        "values": values,
        "different": different[:20],
        "distance_ties": ties,
        "summary": (
            f"{values:,} values of {sum(v['windows'] for v in per_match.values())} windows in "
            f"{len(per_match)} matches equal ({ties} distances 0.1 m apart on an exact .x5)"
            if ok
            else f"{len(different)} values differ"
        ),
    }


def live_delay() -> dict:
    c = Consumer(
        {
            "bootstrap.servers": BOOTSTRAP,
            "group.id": f"evidence-delay-{time.time_ns()}",
            "enable.auto.commit": False,
            "log_level": 3,
        }
    )
    parts = [
        TopicPartition("foot-tracking", p)
        for p in c.list_topics("foot-tracking", timeout=10).topics["foot-tracking"].partitions
    ]
    c.assign([TopicPartition(tp.topic, tp.partition, c.get_watermark_offsets(tp, timeout=10)[1]) for tp in parts])
    producer = subprocess.Popen(
        [sys.executable, "-m", "ingestion.producer_foot", "--match", "m002", "--speed", "1", "--start", "3000"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    delays, t0 = [], time.time()
    while time.time() - t0 < 20:
        for msg in c.consume(500, 0.5):
            if not msg.error():
                delays.append(time.time() * 1000 - msg.timestamp()[1])
    producer.terminate()
    c.close()
    delays.sort()
    p50, p95 = delays[len(delays) // 2], delays[int(len(delays) * 0.95)]
    return {
        "messages": len(delays),
        "p50_ms": round(p50),
        "p95_ms": round(p95),
        "max_ms": round(delays[-1]),
        "page_refresh_s": 1.0,
        "summary": f"a message reaches the app in {p95 / 1000:.2f} s (95 %), and the page redraws every 1 s",
    }


def caught() -> list[dict]:
    query = (
        "{ runsOrError(filter: {statuses: [FAILURE]}) { ... on Runs { results { runId startTime "
        "tags { key value } stepStats { stepKey status } } } } }"
    )
    req = urllib.request.Request(
        DAGSTER, data=json.dumps({"query": query}).encode(), headers={"Content-Type": "application/json"}
    )
    runs = json.loads(urllib.request.urlopen(req, timeout=30).read())["data"]["runsOrError"]["results"]
    out = []
    for r in sorted(runs, key=lambda r: r["startTime"] or 0):
        fix = FIXES.get(r["runId"][:8], {})
        commit = fix.get("fix_commit")
        if commit:
            subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=ROOT, check=True)
        tags = {t["key"]: t["value"] for t in r["tags"]}
        out.append(
            {
                "run_id": r["runId"],
                "match_id": tags.get("dagster/partition"),
                "started": datetime.fromtimestamp(r["startTime"], UTC).strftime("%Y-%m-%d %H:%M UTC")
                if r["startTime"]
                else None,
                "step": ", ".join(s["stepKey"] for s in r["stepStats"] if s["status"] == "FAILURE"),
                "what": fix.get("what", "not explained yet"),
                "fix": fix.get("fix"),
                "fix_commit": commit,
            }
        )
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
    date = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    evidence = {"generated_at": date, "commit": commit + ("+uncommitted changes" if dirty else "")}
    for name, fn in (
        ("live_equals_gold", live_equals_gold),
        ("streaming_equals_gold", streaming_equals_gold),
        ("live_delay", live_delay),
    ):
        log.info("%s ...", name)
        evidence[name] = {"date": date, **fn()}
        log.info("  %s", evidence[name]["summary"])
    evidence["caught"] = caught()
    OUT.write_text(
        "# Written by `make evidence` (scripts/quality_evidence.py): do not edit by hand.\n"
        + yaml.safe_dump(evidence, sort_keys=False, allow_unicode=True, width=120),
        encoding="utf-8",
    )
    log.info("wrote %s", OUT)


if __name__ == "__main__":
    main()
