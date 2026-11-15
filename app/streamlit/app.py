"""MatchLens: one website, five sections (docs/product.md, section 8). Run: `make app` or
`streamlit run app/streamlit/app.py`.

This script is the router: it builds the menu for the view chosen on Home (fan or coach), keeps the view and the match
in st.session_state so they follow the visitor from page to page, and runs the page.
"""
import duckdb
import streamlit as st

import sitemap
from data import CREDIT, library, match_label, table

st.set_page_config(page_title="MatchLens", page_icon=":material/sports_soccer:", layout="wide")
sitemap.style()


def match_choices() -> tuple[list[str], dict[str, str]]:
    """Match ids and their labels, from the library when this Gold file has it."""
    lib = library()
    if lib is not None and not lib.empty:
        return list(lib.match_id), {r.match_id: f"{r.home_team_short} {r.home_score}-{r.away_score} {r.away_team_short}"
                                    f" · {r.match_date:%d %b %Y}" for r in lib.itertuples()}
    teams = table("gold_team_match_stats")
    ids = sorted(teams.match_id.unique())
    return ids, {m: match_label(teams, m) for m in ids}


def sidebar() -> None:
    # "view" and "match_id" are plain session keys, never widget keys: Streamlit may drop a widget's key when the page
    # changes, and both must follow the visitor. The widgets only read them and write the new choice back.
    st.sidebar.markdown("<div class='ml-side-logo'>Match<span>Lens</span></div>", unsafe_allow_html=True)
    view = st.session_state.get("view")
    if view:
        picked = st.sidebar.segmented_control("View", list(sitemap.VIEWS), default=view,
                                              format_func=lambda v: v.capitalize())
        if picked and picked != view:
            st.session_state["view"] = picked
            on_view_page = any(p.key == navigation.url_path and p.section in sitemap.VIEWS.values() for p in sitemap.PAGES)
            if on_view_page:
                st.session_state["go_to"] = sitemap.FIRST_PAGE[picked]   # this page is not in the other view
            st.rerun()          # the menu depends on the view
    try:
        ids, labels = match_choices()
    except duckdb.Error:      # no Gold file yet: every page says what to run
        return
    if not ids:
        return
    current = st.session_state.get("match_id")
    current = current if current in ids else ids[0]
    st.session_state["match_id"] = st.sidebar.selectbox("Match", ids, index=ids.index(current), format_func=labels.get)
    st.sidebar.caption(CREDIT)


pages = {section: [st.Page(f"pages/{p.key}.py", title=p.title, icon=p.icon, url_path=p.key, default=p.key == "home")
                   for p in specs]
         for section, specs in sitemap.menu(st.session_state.get("view")).items()}
navigation = st.navigation(pages)
if "go_to" in st.session_state:
    st.switch_page(st.session_state.pop("go_to"))
sidebar()   # drawn on every page: a widget that is not drawn loses its value, and the match must follow the visitor
navigation.run()
