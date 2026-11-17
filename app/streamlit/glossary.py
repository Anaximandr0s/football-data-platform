"""glossary.py: the words a visitor may not know, explained in one sentence, shown on hover where they appear.
term() for text (st.markdown with HTML), help() for the column tooltips of tables (st.column_config ... help=)."""
import html

TERMS = {
    "xThreat": "Expected threat: how much a pass or a run raised the chance of scoring soon, according to SkillCorner. "
               "It values the option, not the shot: it is not expected goals (xG).",
    "field tilt": "The share of a team's passes made in the opponent's third of the pitch: who played in the other "
                  "team's half.",
    "space control": "The share of the pitch nearer to a player of the team than to any opponent, second by second.",
    "pressing": "How hard a team defends: its pressures, tackles and fouls for every pass the opponent makes.",
    "outfield block": "The 10 players of a team without its goalkeeper: its length is the distance from its deepest to its "
                      "most advanced outfield player.",
    "tracked": "Seen by the broadcast camera. When the camera shows a replay or a close-up, nobody is tracked: those "
               "seconds have no positions.",
}


def term(word: str, label: str | None = None) -> str:
    """The word with a dotted underline and its explanation on hover (HTML, for st.markdown)."""
    return (f"<span class='ml-term' title='{html.escape(TERMS[word], quote=True)}'>"
            f"{html.escape(label or word)}</span>")


def help(word: str) -> str:  # noqa: A001 - the name st.column_config uses
    """The explanation alone, for a table column's tooltip."""
    return TERMS[word]
