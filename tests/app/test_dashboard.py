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


def test_match_story_shows_the_scoreboard_and_the_team_comparison(app_env):
    at = run("pages/match_story.py")
    assert not at.exception
    assert "Home FC" in texts(at) and "Away FC" in texts(at) and "1 - 0" in texts(at)
    assert "Distance (km)" in texts(at) and "Pass accuracy" in texts(at)


def test_player_page_defaults_to_the_most_active_player_and_follows_the_team(app_env):
    at = run("pages/player.py")
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Sprints"] == "4"                       # H01: 4 sprint efforts in the fixture
    assert metrics["Passes"] == "1/2"                      # 1 successful out of 2
    assert metrics["Shots · goals"] == "2 · 1"
    at.radio[0].set_value("AWAY").run()
    assert not at.exception
    assert at.selectbox[0].value in {"A01", "A02"}         # an AWAY player (the match picker belongs to the router)
    assert {m.label: m.value for m in at.metric}["Passes"] == "0/0"


def test_player_ranking_metric_can_change(app_env):
    at = run("pages/player.py")
    ranking = next(s for s in at.selectbox if s.label == "Metric")
    ranking.set_value("sprint_count").run()
    assert not at.exception


def test_team_analysis_lists_the_shots_and_filters_goals(app_env):
    at = run("pages/team_analysis.py")
    assert not at.exception
    assert len(at.dataframe[0].value) == 3                  # shot, goal, AWAY shot
    at.checkbox[0].check().run()
    assert not at.exception and len(at.dataframe[0].value) == 1


def test_team_analysis_pass_network_slider_and_team(app_env):
    at = run("pages/team_analysis.py")
    at.radio[0].set_value("AWAY").run()                     # AWAY made no pass: a message, not a crash
    assert not at.exception
    assert any("No pass" in i.value for i in at.info)


def test_compare_page_asks_for_a_second_match_when_there_is_only_one(app_env):
    at = run("pages/compare_matches.py")
    assert not at.exception
    assert any("Only one match" in i.value for i in at.info)


def test_quality_page_shows_the_last_soda_run(app_env):
    at = run("pages/data_quality.py")
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Passed"] == "2" and metrics["Failed"] == "1"
    assert any("No result for gold" in w.value for w in at.warning)
    assert "detail" in at.dataframe[0].value.columns       # the reason of a failure is shown
    assert "2 failing row(s)" in " ".join(at.dataframe[0].value["detail"])


def test_quality_page_without_any_result_explains_what_to_run(app_env, monkeypatch, tmp_path):
    monkeypatch.setenv("SODA_OUT_DIR", str(tmp_path))
    at = run("pages/data_quality.py")
    assert not at.exception and any("make soda" in i.value for i in at.info)


@pytest.mark.parametrize("page", ["app.py", "pages/match_story.py", "pages/player.py", "pages/team_analysis.py",
                                  "pages/compare_matches.py", "pages/physical_fatigue.py", "pages/match_library.py"])
def test_every_page_explains_what_to_do_when_gold_does_not_exist(page, monkeypatch, tmp_path):
    monkeypatch.setenv("GOLD_DUCKDB_PATH", str(tmp_path / "missing.duckdb"))
    monkeypatch.delenv("GOLD_PARQUET_DIR", raising=False)
    at = run(page)
    assert not at.exception
    assert any("not available" in e.value for e in at.error)


def test_physical_page_shows_the_5_minute_windows_of_a_player(app_env):
    at = run("pages/physical_fatigue.py")
    assert not at.exception
    assert len(at.dataframe[0].value) == 1                 # H01 has one 5-minute window in the fixture


def test_match_library_lists_the_stored_matches_with_their_score_and_date(app_env):
    at = run("pages/match_library.py")
    assert not at.exception
    lib = at.dataframe[0].value
    assert list(lib.home_team) == ["Home FC"] and list(lib.score) == ["1 - 0"]
    assert lib.match_date.iloc[0].strftime("%Y-%m-%d") == "2026-01-01"
    assert {m.label: m.value for m in at.metric}["Matches"] == "1"
