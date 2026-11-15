"""story.py: the plain sentences of the Match story (docs/product.md: F1, F2, F7, E2, F5, F6), built from Gold rows.

Each function returns a Sentence: the text a fan reads and the Gold numbers it was built from, so that every sentence
can be checked against Gold (tests/app/test_story.py and the proof of step 4). Sentences state differences, never
causes: "had more", never "won because". Pure functions: DataFrames in, sentences out.
"""
from dataclasses import dataclass, field

import pandas as pd


@dataclass(frozen=True)
class Sentence:
    text: str
    facts: dict = field(default_factory=dict)


def minute(ts: int) -> int:
    """Match clock minute of a second, as on the live page (ts 0-59 is minute 1)."""
    return int(ts) // 60 + 1


def _other(team: str) -> str:
    return "AWAY" if team == "HOME" else "HOME"


def _pct(v: float) -> str:
    return f"{v:.0%}"


def goals(shots: pd.DataFrame, short: dict, score: tuple[int, int]) -> Sentence:
    """The goals in order: who scored first, who scored last, the final score."""
    g = shots[shots.is_goal].sort_values(["ts", "event_id"])
    final = f"{score[0]}-{score[1]}"
    facts = {"goals": [(minute(r.ts), r.team_id, r.player_short_name) for r in g.itertuples()], "final": final}
    if g.empty:
        return Sentence(f"No goal: the match ended {final}.", facts)
    first, last = g.iloc[0], g.iloc[-1]
    if len(g) == 1:
        return Sentence(f"One goal: {short[first.team_id]} scored it in minute {minute(first.ts)} "
                        f"({first.player_short_name}), final score {final}.", facts)
    return Sentence(f"{len(g)} goals. {short[first.team_id]} scored first (minute {minute(first.ts)}), "
                    f"{short[last.team_id]} scored the last one (minute {minute(last.ts)}): final score {final}.", facts)


def momentum(timeline: pd.DataFrame, short: dict) -> Sentence:
    """E2: SkillCorner xThreat of successful passes per 5-minute window, HOME minus AWAY."""
    w = timeline.pivot(index="window_index", columns="team_id", values="xthreat_successful_passes").fillna(0)
    diff = (w["HOME"] - w["AWAY"]).round(4)
    home_ahead, away_ahead = int((diff > 0).sum()), int((diff < 0).sum())
    leader = "HOME" if home_ahead >= away_ahead else "AWAY"
    best = diff.idxmax() if leader == "HOME" else diff.idxmin()
    facts = {"windows": len(diff), "home_ahead": home_ahead, "away_ahead": away_ahead,
             "best_window": int(best), "best_value": float(diff[best])}
    ahead = home_ahead if leader == "HOME" else away_ahead
    return Sentence(f"{short[leader]} created more danger with its passes in {ahead} of the {len(diff)} five-minute "
                    f"spells; its strongest spell was minutes {best * 5}-{best * 5 + 5}.", facts)


def possession(timeline: pd.DataFrame, profile: pd.DataFrame, short: dict) -> Sentence:
    """F2: the match share, the best reliable spell of the team with more of the ball, and the greyed windows."""
    share = profile.set_index("team_id").possession_share
    greyed = int(timeline[timeline.team_id == "HOME"].possession_greyed.sum())
    if share.isna().all():
        return Sentence("No second with a known owner of the ball: possession cannot be told.", {"greyed_windows": greyed})
    leader = share.idxmax()
    mine = timeline[(timeline.team_id == leader) & ~timeline.possession_greyed]
    facts = {"leader": leader, "share": float(share[leader]), "greyed_windows": greyed}
    text = f"{short[leader]} had the ball {_pct(share[leader])} of the time"
    if mine.empty:
        text += "."
    else:
        best = mine.loc[mine.possession_share.idxmax()]
        facts |= {"best_window": int(best.window_index), "best_share": float(best.possession_share)}
        text += (f"; its best spell was minutes {int(best.window_index) * 5}-{int(best.window_index) * 5 + 5} with "
                 f"{_pct(best.possession_share)}.")
    if greyed:
        text += f" {greyed} spell{'s are' if greyed > 1 else ' is'} greyed: under 60 seconds with a known owner."
    return Sentence(text, facts)


def field_tilt(timeline: pd.DataFrame, profile: pd.DataFrame, short: dict) -> Sentence:
    """F1: in how many spells each team played more passes from the final third, and the match share."""
    tilt = profile.set_index("team_id").field_tilt
    if tilt.isna().all():
        return Sentence("No pass was played from the final third.", {"home": None, "away": None})
    w = timeline.pivot(index="window_index", columns="team_id", values="final_third_passes").fillna(0)
    home_more, away_more = int((w["HOME"] > w["AWAY"]).sum()), int((w["AWAY"] > w["HOME"]).sum())
    leader = tilt.idxmax()
    more = home_more if leader == "HOME" else away_more
    return Sentence(f"{short[leader]} played more passes from the final third than {short[_other(leader)]} in "
                    f"{more} of the {len(w)} five-minute spells, {_pct(tilt[leader])} of them over the match.",
                    {"leader": leader, "home": float(tilt["HOME"]), "away": float(tilt["AWAY"]),
                     "home_more": home_more, "away_more": away_more, "windows": len(w)})


# F7: one sentence per metric, the team with more first; units as a fan reads them
_DIFFERENCES = {
    "possession_share": lambda a, b, A, B: f"{A} had more of the ball: {_pct(a)}, against {_pct(b)} for {B}.",
    "field_tilt": lambda a, b, A, B: (f"{A} played more passes from the final third: {_pct(a)} of them, against "
                                      f"{_pct(b)} for {B}."),
    "shots_and_goals": lambda a, b, A, B: f"{A} had more shots: {a:.0f}, against {b:.0f} for {B} (goals included).",
    "progressive_passes": lambda a, b, A, B: (f"{A} made more passes of 10 m or more toward goal: {a:.0f}, against "
                                              f"{b:.0f} for {B}."),
    "ppp": lambda a, b, A, B: (f"{A} pressed more: {a:.2f} pressures, tackles and fouls per opponent pass, against "
                               f"{b:.2f} for {B}."),
    "dpm_outfield": lambda a, b, A, B: (f"{A}'s outfield players covered more ground: {a:.0f} m per minute of tracked "
                                        f"play, against {b:.0f} for {B}."),
}


def key_differences(profile: pd.DataFrame, short: dict, n: int = 3) -> list[Sentence]:
    """F7: the n largest gaps between the two teams, as sentences."""
    rows = profile.set_index("team_id")
    gaps = []
    for metric, write in _DIFFERENCES.items():
        home, away = rows.loc["HOME", metric], rows.loc["AWAY", metric]
        gap = rows.loc["HOME", f"gap_{metric}"]
        if pd.isna(gap) or gap == 0:
            continue
        lead = "HOME" if home > away else "AWAY"
        a, b = (home, away) if lead == "HOME" else (away, home)
        gaps.append((abs(gap), Sentence(write(a, b, short[lead], short[_other(lead)]),
                                        {"metric": metric, "home": float(home), "away": float(away),
                                         "gap_home": float(gap)})))
    return [s for _, s in sorted(gaps, key=lambda x: -x[0])[:n]]


def shots_line(shots: pd.DataFrame, short: dict) -> Sentence:
    """Shots of each team (goals included), and how far from goal on average."""
    facts, parts = {}, []
    for team in ("HOME", "AWAY"):
        t = shots[shots.team_id == team]
        n, g = len(t), int(t.is_goal.sum())
        dist = float(t.distance_to_goal_m.mean()) if n else None
        facts[team] = {"shots": n, "goals": g, "mean_distance_m": dist}
        where = f" from {dist:.0f} m on average" if n else ""
        parts.append(f"{short[team]} shot {_n(n, 'time')} ({_n(g, 'goal')}){where}")
    return Sentence("; ".join(parts) + ".", facts)


def _n(count: int, word: str, plural: str | None = None) -> str:
    return f"{count} {word if count == 1 else plural or word + 's'}"


def hub(card: pd.DataFrame, team: str, short: dict) -> Sentence | None:
    """F6: the player most involved in the team's successful passes (several only when they tie)."""
    hubs = card[(card.team_id == team) & card.is_hub].sort_values("short_name")
    if hubs.empty:
        return None
    facts = {"players": [(h.player_id, int(h.passes_successful), int(h.passes_received_successful), float(h.involvement))
                         for h in hubs.itertuples()]}
    if len(hubs) > 1:
        return Sentence(f"{' and '.join(hubs.short_name)} shared the hub role of {short[team]}: equally involved in its "
                        f"successful passes.", facts)
    h = hubs.iloc[0]
    return Sentence(f"{h.short_name} was the hub of {short[team]}, the player most involved in its successful passes: "
                    f"{_n(int(h.passes_successful), 'pass', 'passes')} made and {int(h.passes_received_successful)} "
                    f"received.", facts)


def fastest(card: pd.DataFrame, short: dict) -> Sentence | None:
    """F5: top speed from detected positions only (gold_player_card.top_speed_kmh)."""
    c = card.dropna(subset=["top_speed_kmh"])
    if c.empty:
        return None
    f = c.loc[c.top_speed_kmh.idxmax()]
    return Sentence(f"Fastest player: {f.short_name} ({short[f.team_id]}), about {f.top_speed_kmh:.0f} km/h, counting "
                    f"only the positions the camera saw.",
                    {"player_id": f.player_id, "top_speed_kmh": float(f.top_speed_kmh)})
