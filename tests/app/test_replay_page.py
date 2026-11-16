"""The Replay page run headless on the tiny Gold file (the playing itself is in the browser: see docs/notes-fr.md)."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).resolve().parents[2] / "app" / "streamlit"


def test_replay_page_opens_on_the_first_second_with_its_panel(app_env):
    at = AppTest.from_file(str(APP / "sections/replay.py"), default_timeout=90).run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "AT 00:00" in text and "Every 5 minutes" in text and "Space control" in text
    assert at.session_state["replay_sent"]                       # the whole match went to the browser once
    again = at.run()
    assert not again.exception and at.session_state["replay_sent"]


def test_the_match_library_links_to_the_replay(app_env):
    """Through the router: st.page_link needs its menu."""
    at = AppTest.from_file(str(APP / "app.py"), default_timeout=90).run()
    at.session_state["match_id"] = "m1"
    at.switch_page("sections/match_library.py").run()
    assert not at.exception
    assert any("Replay" in getattr(link, "label", "") for link in at.get("page_link"))
