"""Dashboard pages, run headless with Streamlit's AppTest on a real (tiny) Gold file."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("mplsoccer")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).resolve().parents[2] / "app" / "streamlit"


def run(page: str, timeout: int = 90) -> AppTest:
    return AppTest.from_file(str(APP / page), default_timeout=timeout).run()


def texts(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown)


def test_match_story_tells_the_match_in_sentences(app_env):
    at = run("sections/match_story.py")
    assert not at.exception
    page = texts(at)
    assert "<span class='team'>Home</span>" in page and "<span class='score'>1 - 0</span>" in page
    assert "One goal: Home scored it in minute 1 (H. One), final score 1-0." in page      # ts 5
    assert "H. One and H. Two shared the hub role of Home" in page
    assert "won because" not in page and page.count("class='ml-say'") >= 6
    assert "about 28 km/h" in page and "about 30" not in page                    # top speed from detected positions
    assert "It is not xG" in " ".join(c.value for c in at.caption)


def test_player_page_fan_mode_shows_card_badges_scores_pitch_and_f8(app_env):
    at = run("sections/player.py")
    assert not at.exception
    assert at.selectbox[0].value == "H01"                  # the player with the highest distance per minute
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Sprints"] == "4" and metrics["Passes"] == "1"
    page = texts(at)
    assert "1 goal" in page and "Hub of the team" in page
    assert "Top speed about 28 km/h" in page               # 30 km/h joined an estimated position (fixture)
    assert "Not ranked: under 20 tracked minutes" in page
    assert "one stored match only" in " ".join(c.value for c in at.caption)
    assert "COACH MODE" not in page


def test_player_page_follows_the_team_and_the_click_of_the_squad(app_env):
    at = AppTest.from_file(str(APP / "sections/player.py"), default_timeout=90)
    at.session_state["player"] = {"m1": "A02"}             # clicked on the Squad page
    at.run()
    assert not at.exception and at.selectbox[0].value == "A02"
    at.segmented_control[0].set_value("HOME").run()
    assert not at.exception and at.selectbox[0].value in {"H01", "H02"}


def test_player_page_coach_mode_adds_rates_fatigue_events_and_ranking(app_env):
    at = AppTest.from_file(str(APP / "sections/player.py"), default_timeout=90)
    at.session_state["view"] = "coach"
    at.run()
    assert not at.exception
    assert "COACH MODE" in texts(at)
    assert {m.label for m in at.metric} >= {"First 15 min", "Last 5 min", "Drop"}
    events = at.dataframe[-1].value
    assert set(events.type) == {"pass", "shot", "goal"}     # H01's actions; runs are off by default
    next(s for s in at.selectbox if s.label == "Metric").set_value("sprint_count").run()
    assert not at.exception


def test_squad_shows_shirt_cards_by_team_and_opens_the_player_page(app_env):
    at = run("sections/squad.py")
    assert not at.exception
    page = texts(at)
    assert "Home FC" in page and "Away FC" in page and "aria-label='shirt 8'" in page
    buttons = [b for b in at.button if b.label == "Player page"]
    assert len(buttons) == 4
    buttons[0].click().run()
    assert at.session_state["go_to"] == "sections/player.py" and at.session_state["player"]["m1"] in {"H01", "H02"}


def test_team_analysis_lists_the_shots_and_filters_goals(app_env):
    at = run("sections/team_analysis.py")
    assert not at.exception
    assert len(at.dataframe[0].value) == 3                  # shot, goal, AWAY shot
    at.checkbox[0].check().run()
    assert not at.exception and len(at.dataframe[0].value) == 1


def test_team_analysis_pass_network_slider_and_team(app_env):
    at = run("sections/team_analysis.py")
    at.radio[0].set_value("AWAY").run()                     # AWAY made no pass: a message, not a crash
    assert not at.exception
    assert any("No pass" in i.value for i in at.info)


def test_compare_page_asks_for_a_second_match_when_there_is_only_one(app_env):
    at = run("sections/compare_matches.py")
    assert not at.exception
    assert any("Only one match" in i.value for i in at.info)


def test_quality_page_shows_the_last_soda_run(app_env):
    at = run("sections/data_quality.py")
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Passed"] == "2" and metrics["Failed"] == "1"
    assert any("No result for gold" in w.value for w in at.warning)
    assert "detail" in at.dataframe[0].value.columns       # the reason of a failure is shown
    assert "2 failing row(s)" in " ".join(at.dataframe[0].value["detail"])


def test_quality_page_without_any_result_explains_what_to_run(app_env, monkeypatch, tmp_path):
    monkeypatch.setenv("SODA_OUT_DIR", str(tmp_path))
    at = run("sections/data_quality.py")
    assert not at.exception and any("make soda" in i.value for i in at.info)


@pytest.mark.parametrize("page", ["app.py", "sections/match_story.py", "sections/player.py", "sections/team_analysis.py",
                                  "sections/compare_matches.py", "sections/physical_fatigue.py", "sections/match_library.py"])
def test_every_page_explains_what_to_do_when_gold_does_not_exist(page, monkeypatch, tmp_path):
    monkeypatch.setenv("GOLD_DUCKDB_PATH", str(tmp_path / "missing.duckdb"))
    monkeypatch.delenv("GOLD_PARQUET_DIR", raising=False)
    at = run(page)
    assert not at.exception
    assert any("not available" in e.value for e in at.error)


def test_physical_page_shows_the_5_minute_windows_of_a_player(app_env):
    at = run("sections/physical_fatigue.py")
    assert not at.exception
    assert len(at.dataframe[0].value) == 1                 # H01 has one 5-minute window in the fixture


def test_match_library_lists_the_stored_matches_with_their_score_and_date(app_env):
    at = run("sections/match_library.py")
    assert not at.exception
    lib = at.dataframe[0].value
    assert list(lib.home_team) == ["Home FC"] and list(lib.score) == ["1 - 0"]
    assert lib.match_date.iloc[0].strftime("%Y-%m-%d") == "2026-01-01"
    assert {m.label: m.value for m in at.metric}["Matches"] == "1"
