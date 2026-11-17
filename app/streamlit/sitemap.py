"""The MatchLens site map (docs/product.md, section 8): every page, the question it answers, and the menu a visitor
sees for the view chosen on Home. Pure data and functions, except `header`, `coming_soon` and `style`, which draw."""
from dataclasses import dataclass

import streamlit as st

import theme

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
             "What did a stored match look like at any moment?", "both", True),
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
    """One look for every page, light or dark (.streamlit/config.toml): text keeps the theme's colour, lines and
    backgrounds are grey tints, fills come from theme.py. Glossary terms (glossary.term) are underlined with dots."""
    soft, line = "rgba(127,127,127,.08)", "rgba(127,127,127,.35)"
    st.markdown(f"""<style>
    .ml-kicker {{font-size:.8rem; letter-spacing:.16em; font-weight:800; opacity:{theme.MUTED_OPACITY};}}
    .ml-question {{font-size:1.2rem; opacity:{theme.MUTED_OPACITY}; margin-top:-.6rem;}}
    .ml-soon {{border:1px dashed {line}; border-radius:12px; padding:1.1rem 1.3rem; background:{soft};}}
    .ml-soon p {{margin:.4rem 0 0 0;}} .ml-step {{opacity:{theme.MUTED_OPACITY}; font-size:.9rem;}}
    .ml-badge {{background:{theme.GOLD}; color:{theme.ON_FILL}; font-weight:800; font-size:.8rem; letter-spacing:.08em;
               padding:.15rem .55rem; border-radius:999px; text-transform:uppercase;}}
    .ml-tagline {{opacity:{theme.MUTED_OPACITY}; font-size:1.2rem; margin:.5rem 0 1.6rem 0;}}
    .ml-card {{border:1px solid {line}; border-radius:14px; padding:1rem 1.1rem; background:{soft}; height:100%;}}
    .ml-card h3 {{margin:.2rem 0 .3rem 0;}} .ml-card p {{opacity:{theme.MUTED_OPACITY}; margin:0;}}
    .ml-board {{display:flex; align-items:center; gap:.8rem; margin:.5rem 0;}}
    .ml-board .team {{flex:1; font-weight:600; font-size:1rem; line-height:1.25;}} .ml-board .away {{text-align:right;}}
    .ml-board .score {{font-size:1.7rem; font-weight:800; letter-spacing:.06em; white-space:nowrap;}}
    .ml-meta {{opacity:{theme.MUTED_OPACITY}; font-size:.9rem;}}
    .ml-say {{font-size:1.08rem; border-left:4px solid {theme.ACCENT}; padding:.2rem 0 .2rem .8rem;
             margin:.2rem 0 1.4rem 0;}}
    .ml-scoreline {{display:flex; align-items:center; justify-content:center; gap:1.6rem; margin:.4rem 0 .6rem 0;}}
    .ml-scoreline .team {{font-size:1.5rem; font-weight:700; flex:1;}} .ml-scoreline .team:first-child {{text-align:right;}}
    .ml-scoreline .score {{font-size:2.8rem; font-weight:800; letter-spacing:.06em;}}
    .ml-stats {{display:grid; gap:.35rem; margin:.6rem 0;}} .ml-stats div {{display:flex; justify-content:space-between;
               border-bottom:1px solid {line}; padding:.25rem 0;}} .ml-stats span {{opacity:{theme.MUTED_OPACITY};}}
    .ml-stats b {{font-size:1.15rem;}}
    .ml-chip {{display:inline-block; font-size:.85rem; font-weight:700; padding:.15rem .6rem; border-radius:999px;
              margin:.15rem .3rem .15rem 0; letter-spacing:.02em;}}
    .ml-chip-gold {{background:{theme.GOLD}; color:{theme.ON_FILL};}} .ml-chip-info {{background:rgba(127,127,127,.18);}}
    .ml-chip-muted {{background:transparent; opacity:{theme.MUTED_OPACITY}; border:1px dashed {line};}}
    .ml-player {{display:flex; gap:.9rem; align-items:center; margin:.4rem 0 1.4rem 0;}}
    .ml-player .name {{font-weight:700; line-height:1.2;}}
    .ml-cardname {{font-weight:700; margin-top:.2rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}}
    .ml-oneline {{white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}}
    .ml-team {{display:flex; align-items:center; gap:.6rem; margin:1rem 0 .4rem 0;}}
    .ml-team .bar {{width:8px; height:1.6rem; border-radius:3px;}}
    .ml-score-row {{display:grid; grid-template-columns:8.5rem 1fr 2.6rem; gap:.6rem; align-items:center; margin:.35rem 0;}}
    .ml-score-row .track {{height:.6rem; background:rgba(127,127,127,.22); border-radius:999px; overflow:hidden;}}
    .ml-score-row .fill {{height:100%; background:{theme.ACCENT}; border-radius:999px;}}
    .ml-score-row .val {{font-weight:800; text-align:right;}} .ml-score-row.off {{opacity:.45;}}
    .ml-key {{display:inline-flex; align-items:center; gap:.35rem; margin-right:1rem; font-weight:600;}}
    .ml-key i {{width:.95rem; height:.95rem; border-radius:3px; display:inline-block;}}
    .ml-term {{text-decoration:underline dotted; text-underline-offset:3px; cursor:help;}}
    /* the chosen pill: the dark green of the buttons is too dark as text on the dark page, the page's text is not */
    button[data-variant='segmented_control'][aria-checked='true'] {{color:inherit !important; font-weight:700;}}
    </style>""", unsafe_allow_html=True)
