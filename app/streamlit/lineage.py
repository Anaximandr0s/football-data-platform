"""Pipeline & lineage: the Dagster asset graph coloured by one run, and the dbt lineage of one Gold table, as Graphviz
DOT text. Pure functions over the files Dagster writes (data/pipeline/graph.json, runs.json) and the dbt manifest."""
import re

import pandas as pd

# readable on the light and the dark page: transparent background, light fills with dark text, grey lines
BG, BORDER, TEXT, MUTED = "transparent", "#8a948f", "#111111", "#8a948f"
PLAIN = "#eef0ea"
STATE_COLOR = {"done": "#2fbf71", "failed": "#e5484d", "blocked": "#b8c0bc", "not in run": PLAIN}
LAYERS = ("bronze", "silver", "staging", "intermediate", "gold", "report")


def layer(key: str) -> str:
    if key in ("bronze", "silver"):
        return key
    if key.startswith("stg_"):
        return "staging"
    if key.startswith("gold_"):
        return "gold"
    if key == "match_report":
        return "report"
    return "intermediate"            # int_* models and the team_names seed


def step_of(key: str) -> str:
    """The run step that builds an asset: the dbt models all come from the one step `gold`."""
    return key if layer(key) in ("bronze", "silver", "report") else "gold"


def node_states(graph: dict, run: dict | None) -> dict[str, str]:
    """done / failed / blocked (skipped because something before it failed) / not in run, per asset; an asset whose
    Soda check failed is `failed` even though it was built."""
    steps = {s["step"]: s["status"] for s in (run or {}).get("steps", [])}
    failed_checks = {c["asset"] for c in (run or {}).get("checks", []) if not c["passed"]}
    out = {}
    for node in graph["assets"]:
        status = steps.get(step_of(node["key"]))
        out[node["key"]] = ("failed" if node["key"] in failed_checks or status == "FAILURE" else
                            "done" if status == "SUCCESS" else "blocked" if status == "SKIPPED" else "not in run")
    return out


def _attrs(**kw) -> str:
    return "[" + ", ".join(f'{k}="{v}"' for k, v in kw.items()) + "]"


def pipeline_dot(graph: dict, run: dict | None) -> str:
    """The asset graph, one column per layer, each asset coloured by its state in `run`."""
    states = node_states(graph, run)
    lines = ["digraph G {", f'  graph [rankdir=LR, bgcolor="{BG}", nodesep=0.12, ranksep=0.6, fontname="sans-serif"];',
             f'  node [shape=box, style="rounded,filled", fontname="sans-serif", fontsize=10, color="{BORDER}", '
             f'fontcolor="{TEXT}"];', f'  edge [color="{MUTED}", arrowsize=0.6, penwidth=0.7];']
    for name in LAYERS:
        keys = [n for n in graph["assets"] if layer(n["key"]) == name]
        if not keys:
            continue
        lines.append(f'  subgraph cluster_{name} {{ label="{name.upper()}"; fontcolor="{MUTED}"; fontsize=10; '
                     f'color="{BORDER}"; style="rounded";')
        for n in keys:
            checks = [c for c in n["checks"] if c.startswith("soda_")]
            label = n["key"] + ("\\n✓ " + ", ".join(checks) if checks else "")
            lines.append(f'    "{n["key"]}" {_attrs(label=label, fillcolor=STATE_COLOR[states[n["key"]]])};')
        lines.append("  }")
    for n in graph["assets"]:
        for dep in n["deps"]:
            lines.append(f'  "{dep}" -> "{n["key"]}";')
    lines.append("}")
    return "\n".join(lines)


def runs_table(runs: list[dict]) -> pd.DataFrame:
    """One row per run, newest first: when, match, how it started, result, the first step or check that failed."""
    rows = []
    for r in runs:
        failed = [c["check"] + " on " + c["asset"] for c in r.get("checks", []) if not c["passed"]]
        failed += [s["step"] for s in r.get("steps", []) if s["status"] == "FAILURE"]
        skipped = [s["step"] for s in r.get("steps", []) if s["status"] == "SKIPPED"]
        seconds = (r["ended"] - r["started"]) if r.get("started") and r.get("ended") else None
        rows.append({"started": pd.to_datetime(r["started"], unit="s", utc=True) if r.get("started") else pd.NaT,
                     "job": r["job"], "match": r.get("match_id") or "all", "trigger": r["trigger"],
                     "result": "success" if r["status"] == "SUCCESS" else "failed",
                     "minutes": round(seconds / 60, 1) if seconds is not None else None,
                     "what failed": ", ".join(dict.fromkeys(failed)) or "-",
                     "not built": ", ".join(skipped) or "-", "replay": r.get("replay_id") or "-"})
    return pd.DataFrame(rows)


def ancestors(manifest: dict, model: str) -> tuple[list[str], list[tuple[str, str]]]:
    """The dbt nodes a model is built from (itself included) and the edges between them, by name."""
    nodes = {**manifest["nodes"]}
    by_name = {v["name"]: k for k, v in nodes.items() if v["resource_type"] in ("model", "seed")}
    todo, seen, edges = [by_name[model]], set(), set()
    while todo:
        uid = todo.pop()
        if uid in seen:
            continue
        seen.add(uid)
        for parent in nodes[uid].get("depends_on", {}).get("nodes", []):
            if parent in nodes:
                edges.add((nodes[parent]["name"], nodes[uid]["name"]))
                todo.append(parent)
    names = sorted(nodes[u]["name"] for u in seen)
    return names, sorted(edges)


def dbt_dot(manifest: dict, model: str) -> str:
    """The dbt lineage of one model, from the Silver tables it reads to the model itself (highlighted)."""
    names, edges = ancestors(manifest, model)
    lines = ["digraph G {", f'  graph [rankdir=LR, bgcolor="{BG}", nodesep=0.15, ranksep=0.5];',
             f'  node [shape=box, style="rounded,filled", fontname="sans-serif", fontsize=10, color="{BORDER}", '
             f'fontcolor="{TEXT}", fillcolor="{PLAIN}"];', f'  edge [color="{MUTED}", arrowsize=0.6, penwidth=0.7];',
             f'  "silver (Iceberg)" [fillcolor="{STATE_COLOR["blocked"]}"];']
    for name in names:
        fill = STATE_COLOR["done"] if name == model else PLAIN
        lines.append(f'  "{name}" [fillcolor="{fill}"];')
        if name.startswith("stg_"):
            lines.append(f'  "silver (Iceberg)" -> "{name}";')
    lines += [f'  "{a}" -> "{b}";' for a, b in edges]
    lines.append("}")
    return "\n".join(lines)


def overview_dot() -> str:
    """The whole platform in a few boxes: the batch path to the site and the live path, for a first look."""
    node = f'shape=box, style="rounded,filled", fontname="sans-serif", fontsize=20, color="{BORDER}", fontcolor="{TEXT}", margin="0.15,0.08"'
    lines = ["digraph G {", f'  graph [rankdir=LR, bgcolor="{BG}", nodesep=0.25, ranksep=0.35];', f"  node [{node}];",
             f'  edge [color="{MUTED}", arrowsize=0.8, penwidth=1.4, fontname="sans-serif", fontsize=16, '
             f'fontcolor="{MUTED}"];']
    boxes = {"kafka": "Kafka", "bronze": "Bronze\nraw copy", "silver": "Silver\ncleaned", "gold": "Gold\nstatistics",
             "site": "This site", "report": "Report", "stream": "Spark\nStreaming", "stats": "foot-live-stats",
             "live": "Live page"}
    fills = {"silver": STATE_COLOR["done"], "gold": STATE_COLOR["done"], "live": "#f4c430", "site": "#f4c430"}
    for k, label in boxes.items():
        lines.append(f'  {k} [label="{label}", fillcolor="{fills.get(k, PLAIN)}"];')
    lines += ['  kafka -> bronze; bronze -> silver [label="Soda"]; silver -> gold [label="Soda"];',
              "  gold -> site; gold -> report;",
              '  kafka -> stream [label="live"]; stream -> stats; stats -> live; kafka -> live;',
              "  { rank=same; bronze; stream; }", "}"]
    return "\n".join(lines)


# columns every Gold table shares, said once (the contract gives them in its conventions, section 10.2)
COMMON = {
    "match_id": "the match: m001, m002 ...", "team_id": "HOME or AWAY", "event_id": "one event of the match",
    "player_id": "the player, numbered inside this match (H01 ... A16)", "receiver_id": "the player the pass went to",
    "ts": "second of the match since the first kick-off", "period": "1 = first half, 2 = second half",
    "type": "pass, shot, goal, tackle, foul, pressure or run (a run without the ball)", "name": "full name",
    "short_name": "the name shown on screen", "position": "position in the team sheet (GK = goalkeeper)",
    "shirt_number": "shirt number", "team_name": "the team's name", "opponent_name": "the other team's name",
    "competition": "the league", "season": "the season", "round": "the round of the league", "stadium": "the stadium",
    "sprint_seconds": "seconds above 25 km/h", "defensive_actions": "pressures + tackles + fouls",
    "opponent_passes": "passes made by the other team", "progressive_passes": "passes of 10 m or more toward goal",
    "progressive_passes_successful": "progressive passes that reached a team-mate",
    "shots_and_goals": "shots, goals included", "outcome": "how the event ended (successful, unsuccessful ...)",
    "x_start": "where it started, along the pitch (0 = HOME's goal, 105 = AWAY's)", "y_start": "where it started, "
    "across the pitch (0 to 68 m)", "x_end": "where it ended, along the pitch", "y_end": "where it ended, across",
    "phase": "the attacking phase of play (SkillCorner)", "phase_against": "the defending phase of the other team",
    "xthreat": "expected threat of the option (SkillCorner), not expected goals",
    "dangerous": "SkillCorner marks the option as dangerous", "speed_band": "how fast the player moved",
    "subtype": "the kind of run or engagement", "lead_to_shot": "the possession ended with a shot",
    "targeted": "a run the passer looked for", "received": "the run got the ball",
    "player_short_name": "the name shown on screen", "receiver_short_name": "the receiver's name on screen",
    "sprint_count": "sprint efforts: runs of consecutive seconds above 25 km/h", "goals": "goals scored",
    "passes_successful": "passes that reached a team-mate", "passes_received_successful": "passes he received",
}


def contract_meanings(contract: str, table: str) -> dict[str, str]:
    """The meaning of each column of a Gold table, from its table in docs/contrat_donnees.md (section 10.3): a row
    "| a, b | TYPE | meaning |" gives the meaning to both a and b."""
    start = contract.find(f"**{table}**")
    if start < 0:
        return {}
    end = min([i for i in (contract.find("\n**gold_", start + 1), contract.find("\n### ", start + 1)) if i > 0]
              or [len(contract)])
    out = {}
    for line in contract[start:end].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[-1] and cells[0] not in ("Column", "---") and not set(cells[0]) <= {"-"}:
            for name in re.split(r",\s*", cells[0]):
                out[name.strip("` ")] = cells[-1].replace("`", "")
    return {**COMMON, **out}
