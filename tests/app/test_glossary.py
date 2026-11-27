"""The glossary explains the words a visitor may not know: each one is shown on hover somewhere in the site."""

import re
from pathlib import Path

import glossary

APP = Path(__file__).resolve().parents[2] / "app" / "streamlit"


def test_every_glossary_word_is_used_by_a_page():
    code = " ".join(p.read_text(encoding="utf-8") for p in APP.rglob("*.py"))
    used = set(re.findall(r"glossary\.(?:term|help)\(['\"]([^'\"]+)", code))
    assert used == set(glossary.TERMS)


def test_a_term_carries_its_explanation_escaped_for_html():
    span = glossary.term("xThreat")
    assert "class='ml-term'" in span and "not expected goals (xG)" in span and ">xThreat</span>" in span
    assert "'" not in glossary.term("field tilt").split("title='")[1].split("'>")[0]  # quotes cannot break out
