"""coach.py: the plain sentences of the coach pages (docs/product.md: C1-C7, S1, E1), built from Gold rows.

Like story.py, each function returns a Sentence: the text and the Gold numbers it was built from, so every sentence
can be checked against Gold. They describe, they never explain why. Pure functions: DataFrames in, sentences out.
"""
import pandas as pd

from story import Sentence, _n, _other, _pct


def shape(team_shape: pd.DataFrame, team: str, short: dict) -> Sentence | None:
    """C1, C2: width with and without the ball, outfield block length and defensive line out of possession."""
    rows = team_shape[team_shape.team_id == team].set_index("phase")
    inp = rows.loc["in_possession"] if "in_possession" in rows.index else None
    out = rows.loc["out_of_possession"] if "out_of_possession" in rows.index else None
    if inp is None and out is None:
        return None
    facts, parts = {}, []
    if inp is not None:
        facts["width_in"] = float(inp.width)
        parts.append(f"{short[team]} spread {inp.width:.0f} m wide with the ball")
    if out is not None:
        facts |= {"width_out": float(out.width), "length_out": float(out.length),
                  "line_out": float(out.defensive_line_height)}
        lead = f"closed to {out.width:.0f} m without it" if inp is not None else \
            f"{short[team]} was {out.width:.0f} m wide without the ball"
        parts.append(f"{lead}; when {short[_other(team)]} had the ball, its outfield block was {out.length:.0f} m long "
                     f"and its defensive line {out.defensive_line_height:.0f} m from its own goal")
    return Sentence(" and ".join(parts) + ".", facts)


def pressing(pressing_rows: pd.DataFrame, profile: pd.DataFrame, team: str, short: dict) -> Sentence:
    """C3: pressure, tackles and fouls per opponent pass over the match, the most intense 15-minute spell, high press."""
    prof = profile.set_index("team_id").loc[team]
    mine = pressing_rows[(pressing_rows.team_id == team) & pressing_rows.ppp.notna()]
    if mine.empty or pd.isna(prof.ppp):
        return Sentence(f"{short[_other(team)]} made no pass: pressing per opponent pass cannot be measured.",
                        {"ppp": None})
    best = mine.loc[mine.ppp.idxmax()]
    # the counts go with the ratio: a short stoppage window can reach a high ratio on a few passes
    return Sentence(f"{short[team]} made {prof.ppp:.2f} pressures, tackles and fouls per {short[_other(team)]} pass; its "
                    f"most intense spell was {best.window_label}' with {best.ppp:.2f} ({int(best.defensive_actions)} "
                    f"for {_n(int(best.opponent_passes), 'pass', 'passes')}). {_pct(prof.high_press_share)} of them "
                    f"were in the final third.",
                    {"ppp": float(prof.ppp), "best_window": best.window_label, "best_ppp": float(best.ppp),
                     "best_actions": int(best.defensive_actions), "best_passes": int(best.opponent_passes),
                     "high_press_share": float(prof.high_press_share)})


def build_up(build: pd.DataFrame, team: str, short: dict) -> Sentence:
    """C4, C5: progressive passes and the lanes of the final-third entries."""
    b = build.set_index("team_id").loc[team]
    text = (f"{short[team]} made {_n(int(b.progressive_passes), 'pass', 'passes')} of 10 m or more toward goal "
            f"({int(b.progressive_passes_successful)} successful), {b.progressive_passes_per90:.0f} per 90 tracked minutes.")
    facts = {"progressive_passes": int(b.progressive_passes), "successful": int(b.progressive_passes_successful),
             "per90": float(b.progressive_passes_per90), "entries": int(b.final_third_entries)}
    if b.final_third_entries:
        text += (f" Its {int(b.final_third_entries)} successful passes into the final third went {_pct(b.share_left)} "
                 f"left, {_pct(b.share_centre)} centre and {_pct(b.share_right)} right.")
        facts |= {"left": float(b.share_left), "centre": float(b.share_centre), "right": float(b.share_right)}
    return Sentence(text, facts)


def space(space_rows: pd.DataFrame, team: str, short: dict) -> Sentence:
    """S1: share of the pitch nearest to the team, with and without the ball (seconds-weighted over the windows)."""
    s = space_rows[space_rows.team_id == team]

    def mean(col: str, weight: str) -> float:
        w = s[weight].where(s[col].notna(), 0)
        return float((s[col].fillna(0) * w).sum() / w.sum()) if w.sum() else float("nan")

    inp, out = mean("space_share_in_possession", "seconds_in_possession"), \
        mean("space_share_out_of_possession", "seconds_out_of_possession")
    detected = float((s.detected_share * s.seconds_used).sum() / s.seconds_used.sum())
    parts = [f"{_pct(v)} {when}" for v, when in ((inp, "with the ball"), (out, "without it"))
             if v == v]                                   # a phase with no second is left out (nan)
    if not parts:
        parts = [f"{_pct(float((s.space_share * s.seconds_used).sum() / s.seconds_used.sum()))} over the match"]
    return Sentence(f"{short[team]} controlled {parts[0].replace('%', '% of the pitch', 1)}"
                    f"{' and ' + parts[1] if len(parts) > 1 else ''} (the space nearest to its players; "
                    f"{_pct(detected)} of the positions were seen by the camera).",
                    {"in_possession": inp, "out_of_possession": out, "detected_share": detected})


def fatigue(fat: pd.DataFrame, team: str, short: dict) -> Sentence | None:
    """C6: the eligible player who faded most, and how many eligible players ran less at the end."""
    eligible = fat[(fat.team_id == team) & fat.is_eligible]
    if eligible.empty:
        return None
    f = eligible.loc[eligible["drop"].idxmax()]
    less = int((eligible["drop"] > 0).sum())
    return Sentence(f"{f.short_name} faded most in {short[team]}: {f.dpm_first15:.0f} m per minute in his first 15 "
                    f"minutes on the pitch, {f.dpm_last5:.0f} in his last 5 ({_pct(f['drop'])} less). {less} of the "
                    f"{len(eligible)} players with enough data ran less at the end.",
                    {"player_id": f.player_id, "dpm_first15": float(f.dpm_first15), "dpm_last5": float(f.dpm_last5),
                     "drop": float(f["drop"]), "less": less, "eligible": len(eligible)})


def events_summary(ev: pd.DataFrame) -> Sentence:
    """E1: what the filters kept."""
    if ev.empty:
        return Sentence("No event matches these filters.", {"events": 0})
    counts = ev.type.value_counts()
    top = ", ".join(_n(int(n), t, t + "es" if t.endswith("s") else None) for t, n in counts.head(3).items())
    passes = ev[ev.type == "pass"]
    text = f"{_n(len(ev), 'event')} match these filters: {top}."
    facts = {"events": len(ev), "by_type": counts.to_dict()}
    if len(passes):
        ok = float((passes.outcome == "successful").mean())
        text += f" {_pct(ok)} of the passes were successful."
        facts["pass_success"] = ok
    return Sentence(text, facts)


# C7 compare: one sentence per metric, the team's value in each match, the context named
COMPARE = {
    "possession_share": ("had {} of the ball", _pct),
    "field_tilt": ("played {} of the passes from the final third", _pct),
    "width": ("was {} wide on average", lambda v: f"{v:.0f} m"),
    "defensive_line_height": ("defended {} from its own goal", lambda v: f"{v:.0f} m"),
    "ppp": ("made {} pressures, tackles and fouls per opponent pass", lambda v: f"{v:.2f}"),
    "progressive_passes_per90": ("made {} passes of 10 m or more per 90 tracked minutes", lambda v: f"{v:.0f}"),
    "dpm_outfield": ("covered {} per minute of tracked play", lambda v: f"{v:.0f} m"),
}


def compare(profiles: pd.DataFrame, labels: dict, team_name: str, n: int = 3) -> list[Sentence]:
    """C7: the n metrics that changed most (relative) between the first two chosen matches of the team."""
    if len(profiles) < 2:
        return []
    a, b = profiles.iloc[0], profiles.iloc[1]
    gaps = []
    for metric, (verb, fmt) in COMPARE.items():
        va, vb = a[metric], b[metric]
        if pd.isna(va) or pd.isna(vb) or va + vb == 0:
            continue
        gap = abs(va - vb) / ((va + vb) / 2)
        first = labels[a.match_id]
        text = (f"{first[:1].upper() + first[1:]}, {team_name} {verb.format(fmt(va))}; "
                f"{labels[b.match_id]}, {fmt(vb)}.")
        gaps.append((gap, Sentence(text, {"metric": metric, a.match_id: float(va), b.match_id: float(vb)})))
    return [s for _, s in sorted(gaps, key=lambda x: -x[0])[:n]]
