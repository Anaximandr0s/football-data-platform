"""benchmark_report.py (`make benchmark-report`): docs/performance.md and its charts, from the latest results file
written by `make benchmark` (data/benchmark/<date>.json). Pure functions turn the raw measurements into percentiles,
drain times, the capacity limit, SLO verdicts and bottlenecks; only `main` reads and writes files. Run it again at any
time: the report is never edited by hand."""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "data" / "benchmark"
DOC = ROOT / "docs" / "performance.md"
IMG = ROOT / "docs" / "img" / "performance"

SLO = {"live_delay_p95_s": 2.0, "freshness_s": 600.0, "run_success": 0.95}
DRAIN_LIMIT_S = 30.0
TRIGGER_S = 5.0                   # spark/streaming/live_stats.py STREAMING_TRIGGER


# ---------------------------------------------------------------- measures

def percentiles(values: list[float]) -> dict:
    """Nearest-rank percentiles (p is the smallest value with at least p % of the values at or below it)."""
    v = sorted(x for x in values if x is not None and not math.isnan(x))
    if not v:
        return {"n": 0, "p50": None, "p95": None, "p99": None, "max": None}

    def rank(p: float) -> float:
        return v[max(0, math.ceil(p / 100 * len(v)) - 1)]
    return {"n": len(v), "p50": rank(50), "p95": rank(95), "p99": rank(99), "max": v[-1]}


def drain_seconds(samples: list[list[float]], stop: float) -> float | None:
    """samples: [time, messages still to read of what was produced before `stop`]. Seconds after `stop` until nothing
    is left; None if it never happened in the samples."""
    return next((t - stop for t, left in samples if t >= stop and left <= 0), None)


def growing(samples: list[list[float]], start: float, stop: float) -> bool:
    """The lag kept growing during the replay: its smallest value in the last third is above its largest in the first
    third (a reader that keeps up oscillates around a level instead)."""
    third = (stop - start) / 3
    first = [lag for t, lag in samples if start <= t < start + third]
    last = [lag for t, lag in samples if stop - third <= t <= stop]
    return bool(first and last) and min(last) > max(first)


def back_to_normal(samples: list[list[float]], restart: float, baseline: float, hold: float = 10.0) -> float | None:
    """Seconds after `restart` until the lag is at or under `baseline` and stays there for `hold` seconds."""
    after = [(t, lag) for t, lag in samples if t > restart]
    for i, (t, lag) in enumerate(after):
        if lag <= baseline and all(lg <= baseline for t2, lg in after[i:] if t2 <= t + hold) \
                and after[-1][0] >= t + hold:
            return t - restart
    return None


def limit_level(levels: list[dict]) -> int | None:
    """The first load level a reader cannot keep up with: its lag keeps growing, or it needs more than DRAIN_LIMIT_S
    after the producers stop (or never drains in the time measured)."""
    for level in levels:
        for reader in level["readers"].values():
            if reader["growing"] or reader["drain_s"] is None or reader["drain_s"] > DRAIN_LIMIT_S:
                return level["level"]
    return None


def slo_verdicts(r: dict) -> list[dict]:
    x1 = next(s for s in r["speeds"] if s["speed"] == 1)
    p95 = x1["live_delay_ms"]["p95"] / 1000 if x1["live_delay_ms"]["p95"] is not None else None
    fresh = r["freshness"]["gold_ready_s"]
    rel = r["reliability"]
    return [
        {"slo": "Live delay p95 < 2 s", "measured": None if p95 is None else f"{p95:.2f} s (x1)",
         "pass": p95 is not None and p95 < SLO["live_delay_p95_s"]},
        {"slo": "Freshness < 10 min", "measured": None if fresh is None else f"{fresh / 60:.1f} min",
         "pass": fresh is not None and fresh < SLO["freshness_s"]},
        {"slo": "Run success >= 95 %", "measured": f"{rel['success_slo']:.1%} (all runs: {rel['success_raw']:.1%})",
         "pass": rel["success_slo"] >= SLO["run_success"]},
    ]


def bottlenecks(r: dict) -> list[str]:
    """What limits the platform first, each with its evidence, from the numbers only."""
    out = []
    batch = r["spark"]["batch_s"]
    if batch["p50"] is not None and batch["p50"] > TRIGGER_S:
        out.append(f"**Spark Structured Streaming batches** take {batch['p50']:.1f} s (p50, p95 {batch['p95']:.1f} s) "
                   f"for a {TRIGGER_S:.0f} s trigger, sampled while the replays ran: each batch starts late, so "
                   "the 5-minute statistics arrive later than the trigger suggests.")
    level = limit_level(r["load"])
    if level is not None:
        lv = next(x for x in r["load"] if x["level"] == level)
        slow = [(name, rd) for name, rd in lv["readers"].items()
                if rd["growing"] or rd["drain_s"] is None or rd["drain_s"] > DRAIN_LIMIT_S]
        names = ", ".join(f"{n} (" + ("never drained" if rd["drain_s"] is None else f"drain {rd['drain_s']:.0f} s")
                          + (", lag growing" if rd["growing"] else "") + ")" for n, rd in slow)
        out.append(f"**First reader to fall behind**: at {level} matches at x60, {names}.")
    for s in r["speeds"]:
        probe, app = s["live_delay_ms"]["p95"], s["app_p95_ms"]
        if probe and app and app > 2 * probe:
            out.append(f"**The app's own consumer** is slower than the probe running the same code at x{s['speed']}: "
                       f"p95 {app:,.0f} ms against {probe:,.0f} ms. The app measures its lag inside its read loop "
                       "(`live_feed._lag`, every 5 s, one broker round trip per partition): reading waits meanwhile. "
                       "The probe did the same before it was changed and lost about 1.8 s per measure.")
            break
    if r["load"]:
        last = r["load"][-1]
        name, rd = max(last["readers"].items(), key=lambda kv: kv[1]["drain_s"] if kv[1]["drain_s"] is not None
                       else math.inf)
        others = ", ".join(f"{n} {fmt(x['drain_s'], ' s', 1)}" for n, x in last["readers"].items() if n != name)
        out.append(f"**Slowest reader**: {name}, {fmt(rd['drain_s'], ' s', 1)} to drain at {last['level']} matches "
                   f"(peak lag {fmt(rd['peak_lag'])} messages), against {others}.")
    top = sorted(r["load"][-1]["cpu_cores"].items(), key=lambda kv: -kv[1])[:3] if r["load"] else []
    if top:
        out.append("**CPU at the highest load level** (cores, p95): "
                   + ", ".join(f"{n} {v:.2f}" for n, v in top) + ".")
    gold = sorted(r["freshness"]["steps"], key=lambda s: -s["seconds"])
    if gold:
        out.append(f"**After the final whistle**, the longest step is `{gold[0]['step']}` "
                   f"({gold[0]['seconds']:.0f} s of {sum(s['seconds'] for s in gold):.0f} s).")
    read = r["freshness"].get("silver_input")
    if read and read["bronze_copies"] > 1:
        out.append(f"**Silver reads every replay kept in Bronze**: for {r['freshness']['match']}, "
                   f"{read['bronze_copies']} copies, {read['bronze_tracking_rows']:,} tracking rows read to keep "
                   f"{read['kept_tracking_rows']:,}. Bronze only grows (each replay adds a copy), so Silver gets "
                   "slower with every replay of a match, the benchmark's own replays included.")
    return out


# ---------------------------------------------------------------- the document

def fmt(v, unit: str = "", digits: int = 0) -> str:
    return "–" if v is None else f"{v:,.{digits}f}{unit}"


def pct_cells(p: dict, digits: int = 0, unit: str = "") -> str:
    return " | ".join(fmt(p[k], unit, digits) for k in ("p50", "p95", "p99"))


def render(r: dict, charts: list[str]) -> str:
    m = r["machine"]
    lines = [
        "# Performance of the platform",
        "",
        f"Generated by `make benchmark` on {r['generated_at']}, commit `{r['commit']}`. Do not edit: run "
        "`make benchmark` to measure again, `make benchmark-report` to rebuild this page from the last results "
        f"(`data/benchmark/{r['file']}`).",
        "",
        f"Machine: {m['cpu']}, {m['threads']} threads, {m['ram_gib']:.0f} GiB of memory, everything on one laptop "
        "(Docker). Percentiles are nearest-rank over every measured value: p95 = 95 % of the values are at or below it.",
        "",
        "## Service level objectives",
        "",
        "| Objective | Measured | Result |",
        "|---|---|---|",
    ]
    lines += [f"| {v['slo']} | {v['measured'] or '–'} | {'PASS' if v['pass'] else 'FAIL'} |" for v in slo_verdicts(r)]
    lines += ["", "Run success counts the normal runs only; runs started on purpose for tests (tag `purpose`: the "
              "damaged-data demo, the benchmark rebuild) are left out, and the rate of all runs is shown next to it.",
              "", "## Bottlenecks", ""]
    lines += [f"- {b}" for b in bottlenecks(r)] or ["- None found in this run."]

    lines += ["", "## 1. Throughput", "",
              "Rows per second, sampled every 15 s while the replay ran (Prometheus). Target: the rows the match "
              "contains per second of play, times the speed.", "",
              "| Speed | Match, seconds measured | Target msg/s | Kafka msg/s p50 · p95 · p99 | Bronze writer rows/s "
              "p50 · p95 · p99 | Spark rows/s (players query) p50 · p95 · p99 |",
              "|---|---|---|---|---|---|"]
    for s in r["speeds"]:
        lines.append(f"| x{s['speed']} | {s['match']}, {s['seconds']:.0f} s | {s['target_msgs_per_s']:,.0f} | "
                     f"{pct_cells(s['kafka_msgs_per_s']).replace(' | ', ' · ')} | "
                     f"{pct_cells(s['bronze_rows_per_s']).replace(' | ', ' · ')} | "
                     f"{pct_cells(s['spark_rows_per_s']).replace(' | ', ' · ')} |")
    lines += ["", f"![Throughput]({charts[0]})", ""]

    lines += ["## 2. Latency", "",
              "**Producer → Kafka → Live page state**: a consumer running the Live page's own code (`live.route`) "
              "measures, for every message, the time from the producer's send (Kafka timestamp) to the state "
              "updated. The app's own histogram (Prometheus, approximate: buckets) is the cross-check.",
              "**Producer → window complete**: from the send of the first tracking message past a window's end "
              "(+10 s of grace) to the first `foot-live-stats` row of that window marked complete.", "",
              "| Speed | Messages | Live p50 · p95 · p99 · max (ms) | App histogram p95 (ms) | Windows | "
              "Window complete p50 · p95 · p99 (s) |", "|---|---|---|---|---|---|"]
    for s in r["speeds"]:
        d, w = s["live_delay_ms"], s["window_s"]
        lines.append(f"| x{s['speed']} | {fmt(d['n'])} | {pct_cells(d).replace(' | ', ' · ')} · {fmt(d['max'])} | "
                     f"{fmt(s['app_p95_ms'])} | {fmt(w['n'])} | {pct_cells(w, 1).replace(' | ', ' · ')} |")
    f = r["freshness"]
    lines += ["", f"![Latency]({charts[1]})", "",
              f"**Final whistle → Gold ready** ({f['match']} at x60, run `{f['run_id'][:8]}`): "
              f"{fmt(f['gold_ready_s'], ' s')}, the Data quality page's rule (start of the run → end of the `gold` "
              "step). Each step, with its CPU and peak memory (containers `dagster-daemon` and `spark-worker`, where "
              "the Spark driver, its executor and dbt run):", "",
              "| Step | Duration (s) | CPU-seconds | Peak memory (MiB) | Before the run (MiB) |",
              "|---|---|---|---|---|"]
    lines += [f"| `{s['step']}` | {s['seconds']:.1f} | {fmt(s['cpu_s'], '', 1)} | {fmt(s['peak_mib'])} | "
              f"{fmt(s.get('idle_mib'))} |" for s in f["steps"]]
    lines += ["", "CPU-seconds are left out for steps under 30 s: Prometheus reads the counters every 15 s, too coarse to "
              "separate them. Memory is the two containers together; the last column is their memory just before the "
              "run (the daemon and the idle Spark worker)."]
    lines += ["", f"![Final whistle to Gold]({charts[3]})", ""]

    lines += ["## 3. Resources", "",
              f"Silver for one match (steps `silver` + `silver_soda_silver`): "
              f"{fmt(sum(s['cpu_s'] or 0 for s in f['steps'] if s['step'].startswith('silver')), ' CPU-seconds', 0)}, "
              f"peak {fmt(max((s['peak_mib'] or 0 for s in f['steps'] if s['step'].startswith('silver')), default=None), ' MiB')}. "
              f"Gold (steps `gold` + `soda_gold`): "
              f"{fmt(sum(s['cpu_s'] or 0 for s in f['steps'] if 'gold' in s['step']), ' CPU-seconds', 0)}, "
              f"peak {fmt(max((s['peak_mib'] or 0 for s in f['steps'] if 'gold' in s['step']), default=None), ' MiB')}.",
              "",
              f"Peak memory of the whole stack during the benchmark: **{fmt(r['stack_peak_mib'], ' MiB')}** "
              f"(every container, the monitoring included), of {m['ram_gib']:.0f} GiB.", ""]

    lines += ["## 4. Load test", "",
              "1, 2, 3 then 4 different matches replayed at the same time at x60, the Dagster replay sensor paused "
              "(no pipeline run in between). Drain = seconds after the producers stop until the reader has read "
              f"everything; a reader is over the limit when its lag keeps growing or it needs more than "
              f"{DRAIN_LIMIT_S:.0f} s.", "",
              "| Matches | Achieved / target msg/s | Live p95 (ms) | Host CPU p95 | Min. free memory | "
              "Drain: bronze-writer · spark · live page (s) | Lag growing |", "|---|---|---|---|---|---|---|"]
    for lv in r["load"]:
        rd = lv["readers"]
        lines.append(
            f"| {lv['level']} | {lv['achieved_msgs_per_s']:,.0f} / {lv['target_msgs_per_s']:,.0f} | "
            f"{fmt(lv['live_delay_ms']['p95'])} | {fmt(lv['host_cpu']['p95'] * 100 if lv['host_cpu']['p95'] is not None else None, ' %')} | "
            f"{fmt(lv['mem_available_min_mib'], ' MiB')} | "
            + " · ".join(fmt(rd[k]['drain_s'], '', 0) if rd[k]['drain_s'] is not None else "never"
                         for k in ("bronze-writer", "spark", "live-page"))
            + f" | {', '.join(k for k, v in rd.items() if v['growing']) or 'no'} |")
    level = limit_level(r["load"])
    lines += ["", ("**Limit on this laptop: " + (f"{level} matches at x60" if level else
                                                 f"not reached at {len(r['load'])} matches at x60") + ".**"
                   + (f" The run stopped early: {r['safety']['reason']}." if r["safety"]["stopped"] else "")),
              "", f"![Load test]({charts[2]})", ""]

    rel = r["reliability"]
    lines += ["## 5. Reliability", "",
              f"Dagster runs of the last 7 days: {rel['runs']}, success {rel['success_slo']:.1%} without the runs "
              f"started on purpose for tests ({rel['on_purpose']}), {rel['success_raw']:.1%} for all. Step retries used: "
              f"{rel['retries']} (in {rel['runs_with_retries']} run{'' if rel['runs_with_retries'] == 1 else 's'}; Silver and "
              "Gold retry twice, 30 s apart).", "",
              "Recovery: a service restarted in the middle of a replay at x10. Back to normal = its lag at or under "
              "the highest lag of the minute before the restart, for 10 s.", "",
              "| Service restarted | Lag before (max) | Lag peak after | Back to normal after |", "|---|---|---|---|"]
    lines += [f"| {x['service']} | {fmt(x['baseline'])} | {fmt(x['peak'])} | {fmt(x['back_to_normal_s'], ' s')} |"
              for x in r["recovery"]]
    fc = r["final_check"]
    lines += ["", f"After the benchmark, Gold was rebuilt once for the matches of the load test ("
              f"{', '.join(fc['rebuilt'])}): freshness green on every match: {'yes' if fc['freshness_green'] else 'NO'}; "
              f"GoldStale alert firing: {'yes' if fc['goldstale_firing'] else 'no'}.", "",
              "## Limits of this benchmark", "",
              "- One laptop runs everything (Kafka, Spark, Dagster, the app, the monitoring, the producers and this "
              "script): the components compete for the same CPU and memory.",
              "- x1 and x10 measure a 6-minute slice of a match, not the whole match.",
              "- The Live page latency is measured by a consumer running the page's code on the host, not inside the "
              "app container; the app's histogram is the cross-check.",
              "- CPU and memory per step belong to the containers where the step runs, other work included (the "
              "daemon's sensors, the idle worker).", ""]
    return "\n".join(lines)


def charts(r: dict, out: Path) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 15, "axes.titlesize": 18, "axes.titleweight": "bold", "figure.dpi": 110,
                         "axes.spines.top": False, "axes.spines.right": False})
    out.mkdir(parents=True, exist_ok=True)
    blue, orange, green, grey = "#0072B2", "#D55E00", "#009E73", "#8a948f"
    names = []

    fig, ax = plt.subplots(figsize=(11, 5.5))
    speeds = [f"x{s['speed']}" for s in r["speeds"]]
    x = range(len(speeds))
    for i, (key, label, color) in enumerate((("target_msgs_per_s", "target", grey),
                                             ("kafka_msgs_per_s", "Kafka", blue),
                                             ("bronze_rows_per_s", "Bronze writer", orange),
                                             ("spark_rows_per_s", "Spark (players query)", green))):
        vals = [s[key] if key == "target_msgs_per_s" else (s[key]["p50"] or 0) for s in r["speeds"]]
        ax.bar([j + (i - 1.5) * 0.2 for j in x], vals, 0.2, label=label, color=color)
    ax.set_xticks(list(x), speeds)
    ax.set_ylabel("messages per second (p50)")
    ax.set_title("Throughput by replay speed")
    ax.legend(frameon=False)
    names.append(_save(fig, out / "throughput.png"))

    fig, ax = plt.subplots(figsize=(11, 5.5))
    for i, (p, color) in enumerate((("p50", blue), ("p95", orange), ("p99", green))):
        vals = [(s["live_delay_ms"][p] or 0) / 1000 for s in r["speeds"]]
        ax.bar([j + (i - 1) * 0.25 for j in x], vals, 0.25, label=p, color=color)
    ax.axhline(SLO["live_delay_p95_s"], color="#c0392b", linestyle="--", linewidth=2, label="SLO p95 < 2 s")
    ax.set_xticks(list(x), speeds)
    ax.set_ylabel("seconds")
    ax.set_title("Producer to Live page: latency")
    ax.legend(frameon=False)
    names.append(_save(fig, out / "latency.png"))

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5.5))
    levels = [lv["level"] for lv in r["load"]]
    for name, color in (("bronze-writer", orange), ("spark", green), ("live-page", blue)):
        a1.plot(levels, [lv["readers"][name]["peak_lag"] for lv in r["load"]], marker="o", linewidth=3, color=color,
                label=name)
        a2.plot(levels, [lv["readers"][name]["drain_s"] if lv["readers"][name]["drain_s"] is not None else math.nan
                         for lv in r["load"]], marker="o", linewidth=3, color=color, label=name)
    a2.axhline(DRAIN_LIMIT_S, color="#c0392b", linestyle="--", linewidth=2, label=f"limit {DRAIN_LIMIT_S:.0f} s")
    for a, title, unit in ((a1, "Peak lag", "messages"), (a2, "Drain after the replay", "seconds")):
        a.set_xticks(levels)
        a.set_xlabel("matches at the same time (x60)")
        a.set_ylabel(unit)
        a.set_title(title)
    a2.legend(frameon=False)
    fig.suptitle("Load test", fontsize=20, fontweight="bold")
    names.append(_save(fig, out / "load_test.png"))

    fig, ax = plt.subplots(figsize=(11, 4.5))
    colors = [blue, orange, green, "#CC79A7", "#E69F00", "#56B4E9"]
    for s, color in zip(r["freshness"]["steps"], colors * 2, strict=False):    # from its real start: waits show
        ax.barh(["final whistle → Gold"], [s["seconds"]], left=s["start_s"], color=color, label=s["step"])
    ax.axvline(SLO["freshness_s"], color="#c0392b", linestyle="--", linewidth=2, label="SLO 10 min")
    ax.set_xlabel("seconds after the final whistle")
    ax.set_title(f"Final whistle to Gold ready ({r['freshness']['match']}, x60)")
    ax.legend(frameon=False, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.25))
    names.append(_save(fig, out / "freshness_steps.png"))
    return names


def _save(fig, path: Path) -> str:
    fig.tight_layout()
    fig.savefig(path)
    import matplotlib.pyplot as plt
    plt.close(fig)
    return f"img/performance/{path.name}"


def latest_results(folder: Path = RESULTS) -> Path:
    files = sorted(folder.glob("*.json"))
    if not files:
        raise SystemExit("no results yet: run make benchmark")
    return files[-1]


def main() -> None:
    path = latest_results()
    results = {**json.loads(path.read_text(encoding="utf-8")), "file": path.name}
    DOC.write_text(render(results, charts(results, IMG)), encoding="utf-8")
    print(f"{DOC.relative_to(ROOT)} written from {path.name}")


if __name__ == "__main__":
    main()
