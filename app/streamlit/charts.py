"""charts.py: the timelines of the Match story (Altair, drawn by Streamlit in the app theme). Pure: DataFrames in,
charts out. x is the replay clock (ts / 60) so the 5-minute windows keep their width; the axis is labelled on the
football clock (clock.axis_ticks) and a line marks the second kick-off. Goals are marked on every timeline."""
import altair as alt
import pandas as pd

GREY = "#3a4a42"
TEXT = "#b9c8bf"
AXIS_WIDTH = 90   # the same y-axis width on every timeline, so their minutes line up on the page


def _x(end_minute: float, ticks: list[tuple[float, str]]) -> alt.X:
    expr = '""'
    for value, text in reversed(ticks):
        expr = f'datum.value == {value!r} ? "{text}" : {expr}'
    # no scale padding: bar charts would otherwise shift their minute 0 and stop lining up with the goal timeline
    return alt.X("minute:Q", title=None, scale=alt.Scale(domain=[0, end_minute], padding=0, nice=False),
                 axis=alt.Axis(values=[v for v, _ in ticks], labelExpr=expr, grid=False, labelColor=TEXT))


def _half_time(second_kickoff: float | None) -> alt.Chart:
    marks = pd.DataFrame({"minute": [second_kickoff] if second_kickoff is not None else []})
    return alt.Chart(marks).mark_rule(color=TEXT, opacity=0.6, strokeWidth=2).encode(x="minute:Q")


def _goal_rules(goals: pd.DataFrame, colors: dict) -> alt.Chart:
    return alt.Chart(goals).mark_rule(strokeDash=[3, 3], strokeWidth=1.5).encode(
        x="minute:Q", color=alt.Color("team:N", scale=alt.Scale(domain=list(colors), range=list(colors.values())),
                                      legend=None))


def goal_timeline(goals: pd.DataFrame, colors: dict, names: dict, end_minute: float, ticks: list,
                  second_kickoff: float | None) -> alt.Chart:
    """One row per team, a ball at each goal with the scorer and the score after it (HOME labels above, AWAY below)."""
    order = [names["HOME"], names["AWAY"]]
    y = alt.Y("team_name:N", title=None, sort=order, scale=alt.Scale(paddingOuter=0.6),
              axis=alt.Axis(labelColor=TEXT, domain=False, ticks=False, minExtent=AXIS_WIDTH, maxExtent=AXIS_WIDTH))
    color = alt.Color("team:N", scale=alt.Scale(domain=list(colors), range=list(colors.values())), legend=None)
    base = alt.Chart(goals).encode(x=_x(end_minute, ticks), y=y, color=color)
    dots = base.mark_circle(size=280, opacity=1, stroke="#f4c430", strokeWidth=2)
    above = base.transform_filter(alt.datum.team == "HOME").mark_text(dy=-19, color="#e8f0ea", fontSize=12,
                                                                       fontWeight="bold").encode(text="label:N")
    below = base.transform_filter(alt.datum.team == "AWAY").mark_text(dy=21, color="#e8f0ea", fontSize=12,
                                                                       fontWeight="bold").encode(text="label:N")
    track = alt.Chart(pd.DataFrame({"team_name": order})).mark_rule(color=GREY, strokeWidth=1).encode(y=y)
    return (track + _half_time(second_kickoff) + dots + above + below).properties(height=170)


def momentum(timeline: pd.DataFrame, goals: pd.DataFrame, colors: dict, names: dict, end_minute: float, ticks: list,
             second_kickoff: float | None) -> alt.Chart:
    """E2: HOME minus AWAY SkillCorner xThreat of successful passes per 5 minutes; above zero = HOME on top."""
    w = timeline.pivot(index="window_index", columns="team_id", values="xthreat_successful_passes").fillna(0)
    middle = timeline.groupby("window_index").apply(lambda g: (g.window_start_ts.iloc[0] + g.window_end_ts.iloc[0]) / 120,
                                                    include_groups=False)
    df = pd.DataFrame({"minute": middle.loc[w.index].to_numpy(), "momentum": (w["HOME"] - w["AWAY"]).round(3).to_numpy()})
    df["team"] = df.momentum.map(lambda v: "HOME" if v >= 0 else "AWAY")
    df["team_name"] = df.team.map(names)
    bars = alt.Chart(df).mark_bar(width=14, cornerRadius=2).encode(
        x=_x(end_minute, ticks), y=alt.Y("momentum:Q", title=None,
                                  axis=alt.Axis(labelColor=TEXT, titleColor=TEXT, minExtent=AXIS_WIDTH,
                                                maxExtent=AXIS_WIDTH)),
        color=alt.Color("team:N", scale=alt.Scale(domain=list(colors), range=list(colors.values())), legend=None),
        tooltip=[alt.Tooltip("team_name:N", title="on top"), alt.Tooltip("momentum:Q", format=".2f")])
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=TEXT, opacity=0.5).encode(y="y:Q")
    return (bars + zero + _half_time(second_kickoff) + _goal_rules(goals, colors)).properties(height=200)


def shares(timeline: pd.DataFrame, column: str, goals: pd.DataFrame, colors: dict, names: dict, end_minute: float,
           ticks: list, second_kickoff: float | None, greyed: str | None = None) -> alt.Chart:
    """A share per 5-minute window (possession or field tilt), HOME from the bottom; greyed windows drawn in grey."""
    df = timeline[["window_index", "window_start_ts", "window_end_ts", "team_id", column]
                  + ([greyed] if greyed else [])].copy()
    df["minute"] = (df.window_start_ts + df.window_end_ts) / 120            # the middle of the window, in ts minutes
    df["share"] = df[column].fillna(0)
    df["shown"] = df.team_id
    if greyed:
        df.loc[df[greyed], "shown"] = "greyed"
    df["team_name"] = df.team_id.map(names)
    df["order"] = df.team_id.map({"HOME": 0, "AWAY": 1})
    domain, rng = [*colors, "greyed"], [*colors.values(), GREY]
    bars = alt.Chart(df).mark_bar(width=14).encode(
        x=_x(end_minute, ticks),
        y=alt.Y("share:Q", stack="normalize", title=None,
                axis=alt.Axis(format="%", values=[0, 0.5, 1], labelColor=TEXT, minExtent=AXIS_WIDTH,
                              maxExtent=AXIS_WIDTH)),
        color=alt.Color("shown:N", scale=alt.Scale(domain=domain, range=rng), legend=None),
        order=alt.Order("order:Q"),
        tooltip=[alt.Tooltip("team_name:N", title="team"), alt.Tooltip("share:Q", format=".0%")])
    half = alt.Chart(pd.DataFrame({"y": [0.5]})).mark_rule(color="#e8f0ea", opacity=0.35, strokeDash=[2, 2]).encode(
        y="y:Q")
    return (bars + half + _half_time(second_kickoff) + _goal_rules(goals, colors)).properties(height=170)
