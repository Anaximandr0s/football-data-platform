"""Squad (FAN VIEW): the players of the chosen match as shirt cards, grouped by team; a click opens the Player page."""

import streamlit as st

import cards
import sitemap
import viz
from data import current_match, require_gold, table

PER_ROW = 6


def open_player(match_id: str, player_id: str) -> None:
    st.session_state["player"] = {**st.session_state.get("player", {}), match_id: player_id}
    st.session_state["go_to"] = "sections/player.py"


sitemap.header("squad")
teams = require_gold()
match = current_match(teams)
colors = viz.team_colors(teams, match)
card = table("gold_player_card")
card = card[card.match_id == match]
starts = table("gold_player_fatigue")[["match_id", "player_id", "start_ts"]]
card = card.merge(starts, on=["match_id", "player_id"], how="left")
names = {r.team_id: r.team_name for r in teams[teams.match_id == match].itertuples()}

for team in ("HOME", "AWAY"):
    squad = card[card.team_id == team].assign(starter=lambda d: d.start_ts == d.start_ts.min())
    squad = squad.sort_values(["starter", "shirt_number"], ascending=[False, True])
    st.markdown(
        f"<div class='ml-team'><div class='bar' style='background:{colors[team]}'></div>"
        f"<h3 style='margin:0'>{names.get(team, team)}</h3>"
        f"<span class='ml-meta'>{int(squad.starter.sum())} starters · {int((~squad.starter).sum())} substitutes"
        f"</span></div>",
        unsafe_allow_html=True,
    )
    rows = list(squad.itertuples())
    for start in range(0, len(rows), PER_ROW):
        for col, p in zip(st.columns(PER_ROW), rows[start : start + PER_ROW], strict=False):
            with col.container(border=True):
                chips = []
                if p.goals:
                    chips.append(cards.badge(f"{p.goals} goal" + ("s" if p.goals > 1 else ""), "gold"))
                if p.is_hub:
                    chips.append(cards.badge("Hub", "gold"))
                if not p.starter:
                    chips.append(cards.badge("Sub", "muted"))
                st.markdown(
                    f"<div style='text-align:center'>{cards.shirt(colors[team], p.shirt_number, 72)}"
                    f"<div class='ml-cardname'>{p.short_name}</div>"
                    f"<div class='ml-meta ml-oneline'>{p.position} · {p.tracked_minutes:.0f} min tracked</div>"
                    f"<div style='min-height:1.7rem'>{''.join(chips)}</div></div>",
                    unsafe_allow_html=True,
                )
                st.button(
                    "Player page",
                    key=f"open_{p.player_id}",
                    width="stretch",
                    on_click=open_player,
                    args=(match, p.player_id),
                )

st.caption(
    "Hub = the player most involved in the team's successful passes (F6). Tracked minutes = minutes the camera "
    "followed the player."
)
