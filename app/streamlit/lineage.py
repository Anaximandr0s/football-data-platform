"""Pipeline & lineage: the Dagster asset graph coloured by one run, and the dbt lineage of one Gold table, as Graphviz
DOT text. Pure functions over the files Dagster writes (data/pipeline/graph.json, runs.json) and the dbt manifest."""
import pandas as pd

BG, BORDER, TEXT, MUTED = "#0b1410", "#23392d", "#e8f0ea", "#b9c8bf"
STATE_COLOR = {"done": "#15803d", "failed": "#dc2626", "blocked": "#3a4a42", "not in run": "#12221a"}
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
             f'fontcolor="{TEXT}", fillcolor="#12221a"];', f'  edge [color="{MUTED}", arrowsize=0.6, penwidth=0.7];',
             f'  "silver (Iceberg)" [fillcolor="{STATE_COLOR["blocked"]}"];']
    for name in names:
        fill = STATE_COLOR["done"] if name == model else "#12221a"
        lines.append(f'  "{name}" [fillcolor="{fill}"];')
        if name.startswith("stg_"):
            lines.append(f'  "silver (Iceberg)" -> "{name}";')
    lines += [f'  "{a}" -> "{b}";' for a, b in edges]
    lines.append("}")
    return "\n".join(lines)
