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


def test_home_shows_the_scoreboard_and_the_team_comparison(app_env):
    at = run("app.py")
    assert not at.exception
    assert "Home FC" in texts(at) and "Away FC" in texts(at) and "1 - 0" in texts(at)
    assert "Distance (km)" in texts(at) and "Pass accuracy" in texts(at)


def test_players_page_defaults_to_the_most_active_player_and_follows_the_team(app_env):
    at = run("pages/1_Players.py")
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Sprints"] == "4"                       # H01: 4 sprint efforts in the fixture
    assert metrics["Passes"] == "1/2"                      # 1 successful out of 2
    assert metrics["Shots · goals"] == "2 · 1"
    at.radio[0].set_value("AWAY").run()
    assert not at.exception
    assert at.selectbox[0].value in {"A01", "A02"}         # an AWAY player (selectbox 0 = player; the match picker is in the sidebar)
    assert {m.label: m.value for m in at.metric}["Passes"] == "0/0"


def test_players_ranking_metric_can_change(app_env):
    at = run("pages/1_Players.py")
    ranking = next(s for s in at.selectbox if s.label == "Metric")
    ranking.set_value("sprint_count").run()
    assert not at.exception


def test_shots_page_lists_the_shots_and_filters_goals(app_env):
    at = run("pages/2_Shots_and_passes.py")
    assert not at.exception
    assert len(at.dataframe[0].value) == 3                  # shot, goal, AWAY shot
    at.checkbox[0].check().run()
    assert not at.exception and len(at.dataframe[0].value) == 1


def test_shots_page_pass_network_slider_and_team(app_env):
    at = run("pages/2_Shots_and_passes.py")
    at.radio[0].set_value("AWAY").run()                     # AWAY made no pass: a message, not a crash
    assert not at.exception
    assert any("No pass" in i.value for i in at.info)


def test_compare_page_asks_for_a_second_match_when_there_is_only_one(app_env):
    at = run("pages/3_Compare_matches.py")
    assert not at.exception
    assert any("Only one match" in i.value for i in at.info)


def test_quality_page_shows_the_last_soda_run(app_env):
    at = run("pages/4_Data_quality.py")
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Passed"] == "2" and metrics["Failed"] == "1"
    assert any("No result for gold" in w.value for w in at.warning)
    assert "detail" in at.dataframe[0].value.columns       # the reason of a failure is shown
    assert "2 failing row(s)" in " ".join(at.dataframe[0].value["detail"])


def test_quality_page_without_any_result_explains_what_to_run(app_env, monkeypatch, tmp_path):
    monkeypatch.setenv("SODA_OUT_DIR", str(tmp_path))
    at = run("pages/4_Data_quality.py")
    assert not at.exception and any("make soda" in i.value for i in at.info)


@pytest.mark.parametrize("page", ["app.py", "pages/1_Players.py", "pages/2_Shots_and_passes.py", "pages/3_Compare_matches.py"])
def test_every_page_explains_what_to_do_when_gold_does_not_exist(page, monkeypatch, tmp_path):
    monkeypatch.setenv("GOLD_DUCKDB_PATH", str(tmp_path / "missing.duckdb"))
    monkeypatch.delenv("GOLD_PARQUET_DIR", raising=False)
    at = run(page)
    assert not at.exception
    assert any("not available" in e.value for e in at.error)
