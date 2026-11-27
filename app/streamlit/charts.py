"""charts.py: the timelines of the Match story (Altair, drawn by Streamlit in the app theme). Pure: DataFrames in,
charts out. x is the replay clock (ts / 60) so the 5-minute windows keep their width; the axis is labelled on the
football clock (clock.axis_ticks) and a line marks the second kick-off. Goals are marked on every timeline."""

import altair as alt
import pandas as pd

GREY = "#9aa5a0"  # a greyed-out mark (too little data), on both themes
LINE = "#8a948f"  # reference lines (half-time, 50 %, zero): a mark, never text, on both themes
FONT = 14  # every chart text, for the projector
AXIS_WIDTH = 90  # the same y-axis width on every timeline, so their minutes line up on the page


def finish(chart: alt.Chart) -> alt.Chart:
    """Every chart of the site: 14 px text on axes, legends and titles. Colours of the text come from the page's theme
    (Streamlit's chart theme), so a chart reads on the light and the dark page."""
    return (
        chart.configure_axis(labelFontSize=FONT, titleFontSize=FONT)
        .configure_legend(labelFontSize=FONT, titleFontSize=FONT, symbolSize=140)
        .configure_title(fontSize=FONT + 2)
        .configure_header(labelFontSize=FONT, titleFontSize=FONT)
    )


def _x(end_minute: float, ticks: list[tuple[float, str]]) -> alt.X:
    expr = '""'
    for value, text in reversed(ticks):
        expr = f'datum.value == {value!r} ? "{text}" : {expr}'
    # no scale padding: bar charts would otherwise shift their minute 0 and stop lining up with the goal timeline
    return alt.X(
        "minute:Q",
        title=None,
        scale=alt.Scale(domain=[0, end_minute], padding=0, nice=False),
        axis=alt.Axis(values=[v for v, _ in ticks], labelExpr=expr, grid=False),
    )


def _half_time(second_kickoff: float | None, label: bool = False) -> alt.Chart:
    """The second-half kick-off as a line, named on the chart when `label`."""
    marks = pd.DataFrame({"minute": [second_kickoff] if second_kickoff is not None else [], "text": "Half-time"})
    rule = alt.Chart(marks).mark_rule(color=LINE, opacity=0.8, strokeWidth=2).encode(x="minute:Q")
    if not label:
        return rule
    return rule + alt.Chart(marks).mark_text(
        align="left", baseline="top", dx=4, y=2, fontSize=FONT - 1, fontStyle="italic"
    ).encode(x="minute:Q", text="text:N")


def _goal_rules(goals: pd.DataFrame, colors: dict, label: bool = False) -> alt.Chart:
    """A dotted line at each goal in the scoring team's colour, with its minute written at the bottom when `label`."""
    color = alt.Color("team:N", scale=alt.Scale(domain=list(colors), range=list(colors.values())), legend=None)
    rules = alt.Chart(goals).mark_rule(strokeDash=[3, 3], strokeWidth=1.8).encode(x="minute:Q", color=color)
    if not label or goals.empty:
        return rules
    marks = goals.assign(text="⚽ " + goals.label.str.split(" ").str[0])
    return rules + alt.Chart(marks).mark_text(
        baseline="bottom", dy=-2, y=alt.expr("height"), fontSize=FONT - 1, fontWeight="bold"
    ).encode(x="minute:Q", text="text:N")


def _team_labels(names: dict, top: str, bottom: str) -> alt.Chart:
    """The legend written on the chart: which team the upper and the lower half belong to."""
    marks = pd.DataFrame(
        {"text": [f"▲ {names['HOME']} {top}", f"▼ {names['AWAY']} {bottom}"], "where": ["top", "bottom"]}
    )
    up = (
        alt.Chart(marks[marks["where"] == "top"])
        .mark_text(align="left", baseline="top", x=6, y=4, fontSize=FONT, fontWeight="bold")
        .encode(text="text:N")
    )
    down = (
        alt.Chart(marks[marks["where"] == "bottom"])
        .mark_text(align="left", baseline="bottom", x=6, y=alt.expr("height - 22"), fontSize=FONT, fontWeight="bold")
        .encode(text="text:N")
    )
    return up + down


def with_crossings(points: pd.DataFrame, value: str, level: float = 0.5) -> pd.DataFrame:
    """The points plus one point at `level` wherever the straight line between two neighbours crosses it, so an area
    clipped at `level` follows the line exactly. A missing value breaks the line: no crossing is added across it."""
    rows = points[["minute", value]].to_dict("records")
    out = rows[:1]
    for a, b in zip(rows, rows[1:], strict=False):
        va, vb = a[value], b[value]
        if pd.notna(va) and pd.notna(vb) and (va - level) * (vb - level) < 0:
            t = (level - va) / (vb - va)
            out.append({"minute": a["minute"] + t * (b["minute"] - a["minute"]), value: level})
        out.append(b)
    return pd.DataFrame(out, columns=["minute", value])


def balance(
    timeline: pd.DataFrame,
    column: str,
    goals: pd.DataFrame,
    colors: dict,
    names: dict,
    end_minute: float,
    ticks: list,
    second_kickoff: float | None,
    greyed: str | None = None,
) -> alt.Chart:
    """One line: HOME's share per 5-minute window (possession or field tilt) around 50 %. Above the line at 50 % the area
    is HOME's colour, below it AWAY's; the teams, the goals and half-time are written on the chart. A greyed window (too
    few known seconds) has no value: a grey dot at 50 %, no line through it."""
    home = timeline[timeline.team_id == "HOME"].sort_values("window_index").copy()
    home["minute"] = (home.window_start_ts + home.window_end_ts) / 120
    home["share"] = home[column]
    gone = home[greyed].astype(bool) if greyed else home.share.isna()
    home.loc[gone, "share"] = None
    area = with_crossings(home, "share").assign(
        home_part=lambda d: d.share.clip(lower=0.5), away_part=lambda d: d.share.clip(upper=0.5), even=0.5
    )
    x = _x(end_minute, ticks)
    axis = alt.Axis(format="%", values=[0, 0.25, 0.5, 0.75, 1], minExtent=AXIS_WIDTH, maxExtent=AXIS_WIDTH)
    scale = alt.Scale(domain=[0, 1])
    y = alt.Y("share:Q", title=None, scale=scale, axis=axis)
    up = (
        alt.Chart(area)
        .mark_area(color=colors["HOME"], opacity=0.55)
        .encode(x=x, y=alt.Y("home_part:Q", title=None, scale=scale, axis=axis), y2="even:Q")
    )
    down = (
        alt.Chart(area)
        .mark_area(color=colors["AWAY"], opacity=0.55)
        .encode(x=x, y=alt.Y("away_part:Q", title=None, scale=scale, axis=axis), y2="even:Q")
    )
    line = (
        alt.Chart(home)
        .mark_line(color=LINE, strokeWidth=2.5, point=True)
        .encode(
            x=x,
            y=y,
            tooltip=[
                alt.Tooltip("window_label:N", title="minutes"),
                alt.Tooltip("share:Q", title=names["HOME"], format=".0%"),
            ],
        )
    )
    half = alt.Chart(pd.DataFrame({"share": [0.5]})).mark_rule(color=LINE, strokeDash=[2, 2]).encode(y="share:Q")
    layers = [
        up,
        down,
        half,
        line,
        _half_time(second_kickoff, label=True),
        _goal_rules(goals, colors, label=True),
        _team_labels(names, "had more", "had more"),
    ]
    if gone.any():
        layers.append(
            alt.Chart(home[gone].assign(share=0.5))
            .mark_point(color=GREY, size=60, filled=True)
            .encode(x=x, y="share:Q", tooltip=[alt.Tooltip("window_label:N", title="too few seconds to say")])
        )
    return alt.layer(*layers).properties(height=230)


def goal_timeline(
    goals: pd.DataFrame, colors: dict, names: dict, end_minute: float, ticks: list, second_kickoff: float | None
) -> alt.Chart:
    """One row per team, a ball at each goal with the scorer and the score after it (HOME labels above, AWAY below)."""
    order = [names["HOME"], names["AWAY"]]
    y = alt.Y(
        "team_name:N",
        title=None,
        sort=order,
        scale=alt.Scale(paddingOuter=0.6),
        axis=alt.Axis(domain=False, ticks=False, minExtent=AXIS_WIDTH, maxExtent=AXIS_WIDTH),
    )
    color = alt.Color("team:N", scale=alt.Scale(domain=list(colors), range=list(colors.values())), legend=None)
    base = alt.Chart(goals).encode(x=_x(end_minute, ticks), y=y, color=color)
    dots = base.mark_circle(size=280, opacity=1, stroke="#f4c430", strokeWidth=2)
    above = (
        base.transform_filter(alt.datum.team == "HOME")
        .mark_text(dy=-19, fontSize=FONT, fontWeight="bold")
        .encode(text="label:N")
    )
    below = (
        base.transform_filter(alt.datum.team == "AWAY")
        .mark_text(dy=21, fontSize=FONT, fontWeight="bold")
        .encode(text="label:N")
    )
    track = alt.Chart(pd.DataFrame({"team_name": order})).mark_rule(color=GREY, strokeWidth=1).encode(y=y)
    return (track + _half_time(second_kickoff) + dots + above + below).properties(height=170)


def momentum(
    timeline: pd.DataFrame,
    goals: pd.DataFrame,
    colors: dict,
    names: dict,
    end_minute: float,
    ticks: list,
    second_kickoff: float | None,
) -> alt.Chart:
    """E2: HOME minus AWAY SkillCorner xThreat of successful passes per 5 minutes; above zero = HOME on top."""
    w = timeline.pivot(index="window_index", columns="team_id", values="xthreat_successful_passes").fillna(0)
    middle = timeline.groupby("window_index").apply(
        lambda g: (g.window_start_ts.iloc[0] + g.window_end_ts.iloc[0]) / 120, include_groups=False
    )
    df = pd.DataFrame(
        {"minute": middle.loc[w.index].to_numpy(), "momentum": (w["HOME"] - w["AWAY"]).round(3).to_numpy()}
    )
    df["team"] = df.momentum.map(lambda v: "HOME" if v >= 0 else "AWAY")
    df["team_name"] = df.team.map(names)
    bars = (
        alt.Chart(df)
        .mark_bar(width=14, cornerRadius=2)
        .encode(
            x=_x(end_minute, ticks),
            y=alt.Y("momentum:Q", title=None, axis=alt.Axis(minExtent=AXIS_WIDTH, maxExtent=AXIS_WIDTH)),
            color=alt.Color("team:N", scale=alt.Scale(domain=list(colors), range=list(colors.values())), legend=None),
            tooltip=[alt.Tooltip("team_name:N", title="on top"), alt.Tooltip("momentum:Q", format=".2f")],
        )
    )
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=LINE, opacity=0.8).encode(y="y:Q")
    return alt.layer(
        bars,
        zero,
        _half_time(second_kickoff, label=True),
        _goal_rules(goals, colors, label=True),
        _team_labels(names, "more dangerous", "more dangerous"),
    ).properties(height=240)


def space_control(
    space: pd.DataFrame,
    color: str,
    team: str,
    end_minute: float,
    ticks: list,
    second_kickoff: float | None,
    now_minute: float,
) -> alt.Chart:
    """S1 per 5-minute window (gold_space_control of one team), the even line at 50 %, and a gold rule at the minute
    being watched (Replay)."""
    data = space.assign(minute=(space.window_start_ts + space.window_end_ts) / 2 / 60)
    y = alt.Y(
        "space_share:Q",
        title=f"{team}'s share",
        scale=alt.Scale(domain=[0.3, 0.7], clamp=True),
        axis=alt.Axis(format="%", minExtent=AXIS_WIDTH, values=[0.3, 0.5, 0.7]),
    )
    line = (
        alt.Chart(data)
        .mark_line(point=True, color=color)
        .encode(
            x=_x(end_minute, ticks),
            y=y,
            tooltip=[alt.Tooltip("window_label:N", title="minutes"), alt.Tooltip("space_share:Q", format=".0%")],
        )
    )
    even = (
        alt.Chart(pd.DataFrame({"space_share": [0.5]}))
        .mark_rule(color=LINE, strokeDash=[4, 4], opacity=0.5)
        .encode(y=y)
    )
    now = (
        alt.Chart(pd.DataFrame({"minute": [now_minute]})).mark_rule(color="#f4c430", strokeWidth=2).encode(x="minute:Q")
    )
    return (_half_time(second_kickoff) + even + line + now).properties(height=170)


def ranking(df: pd.DataFrame, metric: str, title: str, colors: dict, names: dict, top: int = 10) -> alt.Chart:
    """The top players of one metric, coloured by team, with the value written at the end of each bar."""
    best = df.nlargest(top, metric).assign(team=lambda d: d.team_id.map(names))
    base = alt.Chart(best).encode(
        y=alt.Y(
            "short_name:N",
            sort=list(best.short_name),  # a field sort is lost across layers
            title=None,
            axis=alt.Axis(labelLimit=0),
        ),
        x=alt.X(f"{metric}:Q", title=title),
    )
    bars = base.mark_bar(cornerRadius=3).encode(
        color=alt.Color(
            "team:N",
            scale=alt.Scale(domain=[names["HOME"], names["AWAY"]], range=[colors["HOME"], colors["AWAY"]]),
            legend=alt.Legend(orient="top", title=None),
        ),
        tooltip=["short_name:N", "team:N", alt.Tooltip(f"{metric}:Q", title=title, format=".3~f")],
    )
    values = base.mark_text(align="left", dx=5, fontSize=FONT, fontWeight="bold").encode(
        text=alt.Text(f"{metric}:Q", format=".3~f")
    )
    return (bars + values).properties(height=34 * len(best))
