"""The MatchLens site map (docs/product.md, section 8): every page, the question it answers, and the menu a visitor
sees for the view chosen on Home. Pure data and functions, except `header`, `coming_soon` and `style`, which draw."""
from dataclasses import dataclass

import streamlit as st

VIEWS = {"fan": "FAN VIEW", "coach": "COACH VIEW"}
FIRST_PAGE = {"fan": "sections/match_story.py", "coach": "sections/team_analysis.py"}   # where a view opens
SECTIONS = ("", "LIVE", "MATCHES", "FAN VIEW", "COACH VIEW", "BEHIND THE DATA")


@dataclass(frozen=True)
class PageSpec:
    key: str        # file sections/<key>.py and URL path
    title: str
    icon: str
    section: str
    question: str
    persona: str
    ready: bool     # False: the page says "coming soon" and the step that builds it


PAGES = (
    PageSpec("home", "Home", ":material/sports_soccer:", "", "Who am I, and which match do I look at?", "both", True),
    PageSpec("live_match", "Live match", ":material/sensors:", "LIVE",
             "What is happening right now, and how is this player doing so far?", "both", True),
    PageSpec("match_library", "Match library", ":material/video_library:", "MATCHES",
             "Which matches are stored, and how did they end?", "both", True),
    PageSpec("replay", "Replay", ":material/replay:", "MATCHES",
             "What did a stored match look like at any moment?", "both", False),
    PageSpec("compare_matches", "Compare matches", ":material/compare_arrows:", "MATCHES",
             "Is this how a team usually plays?", "both", True),
    PageSpec("match_story", "Match story", ":material/auto_stories:", "FAN VIEW",
             "How did the match go, and why did it end this way?", "fans", True),
    PageSpec("squad", "Squad", ":material/groups:", "FAN VIEW", "Who played?", "fans", True),
    PageSpec("player", "Player page", ":material/person:", "FAN VIEW", "How did this player play?", "fans", True),
    PageSpec("team_analysis", "Team analysis", ":material/strategy:", "COACH VIEW",
             "How does the team organise, press and attack?", "coaches", True),
    PageSpec("physical_fatigue", "Physical & fatigue", ":material/directions_run:", "COACH VIEW",
             "Who ran how much, and who faded?", "coaches", True),
    PageSpec("event_explorer", "Event explorer", ":material/scatter_plot:", "COACH VIEW",
             "Which actions happened where, by whom, and how dangerous were they?", "coaches", True),
    PageSpec("player", "Player page", ":material/person:", "COACH VIEW", "What exactly did this player do?",
             "coaches", True),
    PageSpec("data_quality", "Data quality", ":material/verified:", "BEHIND THE DATA", "Can I trust these numbers?",
             "jury", True),
    PageSpec("pipeline_lineage", "Pipeline & lineage", ":material/account_tree:", "BEHIND THE DATA",
             "How does a number get from the camera to the screen?", "jury", True),
    PageSpec("sources_limits", "Sources & limits", ":material/menu_book:", "BEHIND THE DATA",
             "Where does the data come from, and what can it not tell?", "jury", True),
)

# what is still missing on a page that exists, and the build step of docs/product.md section 12 that adds it
COMING = {
    "replay": ("play a stored match at 0.25x to 8x with trails, Voronoi cells and a stats panel on click", 7),
}


def menu(view: str | None) -> dict[str, list[PageSpec]]:
    """Sections in menu order. Only the chosen view's section is shown; none before a view is chosen."""
    shown = [s for s in SECTIONS if s not in VIEWS.values() or s == VIEWS.get(view)]
    return {s: [p for p in PAGES if p.section == s] for s in shown}


def spec(key: str, view: str | None = None) -> PageSpec:
    """The page `key` as listed for `view` (the Player page has a fan and a coach entry)."""
    matches = [p for p in PAGES if p.key == key]
    return next((p for p in matches if p.section == VIEWS.get(view)), matches[0])


def header(key: str) -> PageSpec:
    """Title and question of the page, the same on every page."""
    page = spec(key, st.session_state.get("view"))
    st.markdown(f"<div class='ml-kicker'>{page.section or 'MATCHLENS'}</div>", unsafe_allow_html=True)
    st.title(page.title)
    st.markdown(f"<p class='ml-question'>{page.question}</p>", unsafe_allow_html=True)
    return page


def coming_soon(key: str) -> None:
    """A page that is not built yet: its question, what it will show and when."""
    what, step = COMING[key]
    st.markdown(f"<div class='ml-soon'><span class='ml-badge'>Coming soon</span><p>It will show {what}.</p>"
                f"<p class='ml-step'>Build step {step} of docs/product.md, section 12.</p></div>",
                unsafe_allow_html=True)


def still_to_come(key: str) -> None:
    """What a page that already shows something will add later."""
    what, step = COMING[key]
    st.caption(f"Still to come (build step {step}): {what}.")


def style() -> None:
    """One look for every page: the stadium-at-night theme of .streamlit/config.toml, plus a few classes."""
    st.markdown("""<style>
    .ml-kicker {font-size:.75rem; letter-spacing:.18em; color:var(--ml-accent, #3ddc84); font-weight:700;}
    .ml-question {font-size:1.15rem; color:#b9c8bf; margin-top:-.6rem;}
    .ml-soon {border:1px dashed #2f4a3c; border-radius:12px; padding:1.1rem 1.3rem; background:#0f1d16;}
    .ml-soon p {margin:.4rem 0 0 0; color:#d5e2da;} .ml-step {color:#8fa69a !important; font-size:.85rem;}
    .ml-badge {background:#f4c430; color:#0b1410; font-weight:700; font-size:.75rem; letter-spacing:.08em;
               padding:.15rem .55rem; border-radius:999px; text-transform:uppercase;}
    .ml-logo {font-weight:800; font-size:3.6rem; letter-spacing:-.03em; line-height:1.05; margin:.2rem 0 0 0;}
    .ml-logo span {color:#3ddc84;}
    .ml-tagline {color:#b9c8bf; font-size:1.15rem; margin:.5rem 0 1.6rem 0;}
    .ml-side-logo {font-weight:800; font-size:1.5rem; letter-spacing:-.02em;} .ml-side-logo span {color:#3ddc84;}
    .ml-card {border:1px solid #23392d; border-radius:14px; padding:1rem 1.1rem; background:#0f1d16; height:100%;}
    .ml-card h3 {margin:.2rem 0 .3rem 0;} .ml-card p {color:#b9c8bf; margin:0;}
    .ml-board {display:flex; align-items:center; gap:.8rem; margin:.5rem 0;}
    .ml-board .team {flex:1; font-weight:600; font-size:1rem; line-height:1.25;} .ml-board .away {text-align:right;}
    .ml-board .score {font-size:1.7rem; font-weight:800; letter-spacing:.06em; white-space:nowrap;}
    .ml-meta {color:#8fa69a; font-size:.85rem;}
    .ml-say {font-size:1.05rem; color:#e8f0ea; border-left:3px solid #3ddc84; padding:.2rem 0 .2rem .8rem;
             margin:.2rem 0 1.4rem 0;}
    .ml-scoreline {display:flex; align-items:center; justify-content:center; gap:1.6rem; margin:.4rem 0 .6rem 0;}
    .ml-scoreline .team {font-size:1.5rem; font-weight:700; flex:1;} .ml-scoreline .team:first-child {text-align:right;}
    .ml-scoreline .score {font-size:2.8rem; font-weight:800; letter-spacing:.06em;}
    .ml-stats {display:grid; gap:.35rem; margin:.6rem 0;} .ml-stats div {display:flex; justify-content:space-between;
               border-bottom:1px solid #1d3b2c; padding:.25rem 0;} .ml-stats span {color:#b9c8bf;}
    .ml-stats b {font-size:1.15rem;}
    .ml-chip {display:inline-block; font-size:.78rem; font-weight:700; padding:.15rem .6rem; border-radius:999px;
              margin:.15rem .3rem .15rem 0; letter-spacing:.02em;}
    .ml-chip-gold {background:#f4c430; color:#0b1410;} .ml-chip-info {background:#1d3b2c; color:#d5e2da;}
    .ml-chip-muted {background:transparent; color:#8fa69a; border:1px dashed #2f4a3c;}
    .ml-player {display:flex; gap:.9rem; align-items:center; margin:.4rem 0 1.4rem 0;}
    .ml-player .name {font-weight:700; line-height:1.2;}
    .ml-cardname {font-weight:700; margin-top:.2rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
    .ml-oneline {white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
    .ml-team {display:flex; align-items:center; gap:.6rem; margin:1rem 0 .4rem 0;}
    .ml-team .bar {width:6px; height:1.6rem; border-radius:3px;}
    .ml-score-row {display:grid; grid-template-columns:8.5rem 1fr 2.6rem; gap:.6rem; align-items:center; margin:.35rem 0;}
    .ml-score-row .track {height:.6rem; background:#1d3b2c; border-radius:999px; overflow:hidden;}
    .ml-score-row .fill {height:100%; background:#3ddc84; border-radius:999px;}
    .ml-score-row .val {font-weight:800; text-align:right;} .ml-score-row.off {opacity:.45;}
    </style>""", unsafe_allow_html=True)
