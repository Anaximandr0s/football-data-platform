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
    assert "about 27 km/h" in page and "about 30" not in page                    # held over two detected seconds
    assert "It is not xG" in " ".join(c.value for c in at.caption)


def test_player_page_fan_mode_shows_card_badges_scores_pitch_and_f8(app_env):
    at = run("sections/player.py")
    assert not at.exception
    assert at.selectbox[0].value == "H01"                  # the player with the highest distance per minute
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Sprints"] == "4" and metrics["Passes"] == "1"
    page = texts(at)
    assert "1 goal" in page and "Hub of the team" in page
    assert "Top speed about 27 km/h" in page               # held over two detected seconds (fixture)
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


def test_team_analysis_tells_shape_pressing_build_up_and_space(app_env):
    at = run("sections/team_analysis.py")
    assert not at.exception
    page = texts(at)
    assert "Outfield block length" in page and "Defensive line from own goal" in page
    assert "Home spread 10 m wide with the ball." in page                # only ts 0 has a known owner: HOME
    assert "nan" not in page
    assert "Away made no pass: pressing per opponent pass cannot be measured." in page
    assert "Home made 2 passes of 10 m or more toward goal (1 successful)" in page
    assert "controlled" in page and len(at.dataframe[0].value) == 2       # HOME's shot and goal


def test_team_analysis_follows_the_other_team(app_env):
    at = run("sections/team_analysis.py")
    at.segmented_control[0].set_value("AWAY").run()
    assert not at.exception
    assert "Away made 0 passes of 10 m or more" in texts(at) and len(at.dataframe[0].value) == 1


def test_compare_page_needs_two_matches_of_the_team(app_env):
    at = run("sections/compare_matches.py")
    assert not at.exception
    assert any("has only one stored match" in i.value for i in at.info)


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


def test_physical_page_shows_the_team_grid_fatigue_and_one_player(app_env):
    at = run("sections/physical_fatigue.py")
    assert not at.exception
    fatigue, one = at.dataframe[0].value, at.dataframe[1].value
    assert set(fatigue.player) == {"#8 H. One", "#4 H. Two"} and not fatigue["enough data"].any()
    assert list(one.minutes) == ["0-5'"]                     # H01: the 101-second first-half window of the fixture
    assert "faded most" not in texts(at)                       # nobody passes the C6 thresholds in the fixture


def test_match_library_lists_the_stored_matches_with_their_score_and_date(app_env):
    at = run("sections/match_library.py")
    assert not at.exception
    lib = at.dataframe[0].value
    assert list(lib.home_team) == ["Home FC"] and list(lib.score) == ["1 - 0"]
    assert lib.match_date.iloc[0].strftime("%Y-%m-%d") == "2026-01-01"
    assert {m.label: m.value for m in at.metric}["Matches"] == "1"


def test_event_explorer_filters_summarises_and_compares(app_env):
    at = run("sections/event_explorer.py")
    assert not at.exception
    summary = at.dataframe[0].value
    assert dict(summary["count"]) == {"pass": "3", "shot": "1", "goal": "1"}   # HOME, passes shots goals by default
    assert summary.loc["pass", "success"] == "67%" and summary.loc["shot", "success"] == "-"   # "-", never None
    assert "5 events match these filters: 3 passes, 1 shot, 1 goal. 67% of the passes were successful." in texts(at)
    at.multiselect[0].set_value(["run"]).run()                                  # runs are events too
    assert not at.exception and dict(at.dataframe[0].value["count"]) == {"run": "1"}
    at.segmented_control[2].set_value("Heatmap").run()
    assert not at.exception
