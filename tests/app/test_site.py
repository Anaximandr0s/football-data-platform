"""The MatchLens site: the menu per view (pure), and the router run headless on the tiny Gold file."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

import sitemap  # noqa: E402

APP = Path(__file__).resolve().parents[2] / "app" / "streamlit"


def titles(menu: dict) -> dict[str, list[str]]:
    return {section: [p.title for p in pages] for section, pages in menu.items()}


def test_menu_shows_only_the_chosen_view():
    assert list(sitemap.menu(None)) == ["", "LIVE", "MATCHES", "BEHIND THE DATA"]
    fan, coach = titles(sitemap.menu("fan")), titles(sitemap.menu("coach"))
    assert list(fan) == ["", "LIVE", "MATCHES", "FAN VIEW", "BEHIND THE DATA"]
    assert fan["FAN VIEW"] == ["Match story", "Squad", "Player page"] and "COACH VIEW" not in fan
    assert coach["COACH VIEW"] == ["Team analysis", "Physical & fatigue", "Event explorer", "Player page"]
    assert fan["MATCHES"] == ["Match library", "Replay", "Compare matches"]
    assert fan["BEHIND THE DATA"] == ["Data quality", "Pipeline & lineage", "Sources & limits"]


def test_every_page_has_a_file_and_every_unfinished_page_says_what_comes():
    for page in sitemap.PAGES:
        assert (APP / "pages" / f"{page.key}.py").exists(), page.key
        assert page.ready or page.key in sitemap.COMING
    for view in (None, "fan", "coach"):              # one URL per page in any menu
        keys = [p.key for pages in sitemap.menu(view).values() for p in pages]
        assert len(keys) == len(set(keys))


def test_the_player_page_asks_its_question_for_the_view():
    assert sitemap.spec("player", "fan").question == "How did this player play?"
    assert sitemap.spec("player", "coach").question == "What exactly did this player do?"


def router(timeout: int = 90) -> AppTest:
    return AppTest.from_file(str(APP / "app.py"), default_timeout=timeout)


def test_home_offers_a_match_and_both_views(app_env):
    at = router().run()
    assert not at.exception
    page = " ".join(m.value for m in at.markdown)
    assert "Match<span>Lens</span>" in page and "<div class='score'>1 - 0</div>" in page
    labels = [b.label for b in at.button]
    assert "Open the fan view" in labels and "Open the coach view" in labels
    assert at.session_state["match_id"] == "m1"                # the first match until one is chosen


def test_choosing_a_view_asks_for_its_first_page_and_pages_keep_view_and_match(app_env):
    at = router().run()
    next(b for b in at.button if b.label == "Open the coach view").click().run()
    assert not at.exception
    # AppTest reruns only the page after its first run, so the router's move to the page is checked in a browser
    assert at.session_state["view"] == "coach" and at.session_state["go_to"] == "pages/team_analysis.py"
    at.switch_page("pages/physical_fatigue.py").run()
    assert not at.exception
    assert at.session_state["view"] == "coach" and at.session_state["match_id"] == "m1"
    assert any("Who ran how much" in m.value for m in at.markdown)


@pytest.mark.parametrize("key", [p.key for p in sitemap.PAGES if not p.ready])
def test_unfinished_pages_say_coming_soon_with_their_question(key, app_env):
    at = router()
    at.session_state["view"] = "coach" if key == "event_explorer" else "fan"
    at.run().switch_page(f"pages/{key}.py").run()
    assert not at.exception
    shown = " ".join(m.value for m in at.markdown)
    assert "Coming soon" in shown and sitemap.spec(key).question in shown

