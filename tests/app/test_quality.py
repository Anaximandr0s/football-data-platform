"""The Data quality page (app/streamlit/quality.py): the six dimensions, the match grid, accuracy against official
sources, freshness from the Dagster runs, what the checks caught; and the page run headless."""
import json
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("streamlit")
yaml = pytest.importorskip("yaml")
from streamlit.testing.v1 import AppTest  # noqa: E402

import quality  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app" / "streamlit"
MAPPING = {"silver_events": {"events have one row per event_id": {"dimension": "uniqueness", "plain": "one row per event"},
                             "goals equal": {"dimension": "accuracy", "plain": "goals equal the real score"}}}


def results(outcome="pass"):
    return {"silver": {"finished_at_utc": "2026-11-17T10:00:00Z", "checks": [
        {"name": "events have one row per event_id", "table": "silver_events", "outcome": outcome},
        {"name": "goals equal", "table": "silver_events", "outcome": "pass"}]}}


def test_the_verdict_says_ready_or_what_failed_in_plain_words():
    ok = quality.checks_table(results(), MAPPING)
    assert list(ok.check) == ["one row per event", "goals equal the real score"]
    assert quality.verdict(ok, "17 Nov 2026", 4) == (
        "green", "The data is ready to use · 2 of 2 checks passed · last check 17 Nov 2026 · 4 matches")
    bad = quality.checks_table(results("fail"), MAPPING)
    status, text = quality.verdict(bad, "17 Nov 2026", 4)
    assert status == "red" and text.startswith("1 of 2 checks failed (uniqueness)")


def kept_rows(silver_tracking=100, gold_players=100):
    report = {"prepared_rows": {"tracking": 100, "ball": 5}, "silver_rows": {"tracking": silver_tracking, "ball": 5},
              "replay_copies_removed": {"tracking": 300, "ball": 15}, "positions_corrected": 3, "speeds_rejected": 0,
              "tracking_rows": silver_tracking}
    return quality.kept({"m1": report}, pd.DataFrame([{"match_id": "m1", "players": gold_players, "balls": 5}]))


def test_completeness_judges_what_our_pipeline_kept_never_the_camera():
    assert kept_rows().kept_share.iloc[0] == 1.0
    assert kept_rows(silver_tracking=90, gold_players=90).kept_share.iloc[0] == pytest.approx(95 / 105)
    assert kept_rows(gold_players=99).kept_share.iloc[0] < 1                 # Gold lost a Silver row
    checks = quality.checks_table(results(), MAPPING)
    lib = pd.DataFrame([{"match_id": "m1", "tracked_share": 0.6, "speeds_rejected": 0}])
    acc = pd.DataFrame(columns=["match_id", "what", "ours", "sources", "status", "scorer_agrees"])
    card = quality.cards(checks, kept_rows(), lib, acc, [], None, None, "now")[0]
    assert (card.status, card.number) == ("green", "100%")                    # 60 % seen by the camera: not judged
    assert "the camera saw 60%" in card.lines[1]
    grid = quality.grid(["m1"], checks, kept_rows(), acc, [])
    assert grid.completeness.iloc[0] == "green" and grid.validity.iloc[0] == "orange"     # 3 positions corrected
    assert quality.grid(["m1"], checks, kept_rows(90, 90), acc, []).completeness.iloc[0] == "red"


def test_a_goal_minute_is_exact_when_one_source_gives_it_and_possession_within_one_point():
    external = {"sources": {"a": {"name": "Club", "url": "u"}, "b": {"name": "AAP", "url": "v"}},
                "matches": {"m1": {"goals": [{"scorer": "S. Klein", "sources": {"a": 50}},          # time order
                                             {"scorer": "A. Goodwin", "sources": {"a": 63, "b": 62}}],
                                   "possession": {"sources": {"a": 0.39}}}}}
    events = pd.DataFrame([dict(match_id="m1", type="goal", ts=3691, period=2, player_short_name="A. Goodwin"),
                           dict(match_id="m1", type="goal", ts=3006, period=2, player_short_name="S. Klein")])
    lib = pd.DataFrame([{"match_id": "m1", "p1_start_ts": 0, "p2_start_ts": 2700}])
    profile = pd.DataFrame([{"match_id": "m1", "team_id": "HOME", "possession_share": 0.40}])
    acc = quality.accuracy(external, events, lib, profile)
    assert list(acc.status) == ["orange", "green", "green"]                 # 51' vs 50'; 62' is one source's
    assert list(acc.ours) == ["51'", "62'", "40.0%"] and acc.scorer_agrees.all()
    assert quality.accuracy(external, events, lib, profile.assign(possession_share=0.405)).status.iloc[-1] == "orange"
    assert quality.accuracy(external, events, lib, profile.assign(possession_share=0.43)).status.iloc[-1] == "red"


def run(rid, match, start, status="SUCCESS", gold=(60, 120), replay=True):
    steps = [{"step": "gold", "status": "SUCCESS" if gold else "SKIPPED", "start": start + gold[0] if gold else None,
              "end": start + gold[1] if gold else None}]
    return {"run_id": rid, "match_id": match, "status": status, "started": start, "ended": start + 300,
            "replay_id": f"{match}-2026111{rid}T000000Z" if replay else None, "steps": steps}


def test_freshness_is_gold_rebuilt_after_the_latest_replay():
    assert quality.freshness([run("1", "m1", 1000)], "m1")[:2] == ("green", 120)
    assert quality.freshness([run("1", "m1", 1000, gold=(60, 900))], "m1")[0] == "orange"    # 15 minutes
    stale = [run("1", "m1", 1000), run("2", "m1", 5000, status="FAILURE", gold=None)]
    assert quality.freshness(stale, "m1")[0] == "red"                    # the latest replay never reached Gold
    rebuilt = stale + [run("3", "m2", 5100, gold=(10, 200))]              # another match's run rebuilt all of Gold
    assert quality.freshness(rebuilt, "m1")[:2] == ("green", 300)
    assert quality.freshness([], "m1")[0] == "grey"


def test_caught_runs_say_what_was_stopped_and_the_fix():
    runs = [{"run_id": "18bf663e-x", "match_id": "m3", "status": "FAILURE", "started": 1,
             "steps": [{"step": "silver", "status": "FAILURE"}, {"step": "gold", "status": "SKIPPED"}]},
            {"run_id": "ok", "status": "SUCCESS", "steps": []}]
    evidence = {"caught": [{"run_id": "18bf663e-x", "what": "the speed gate counted copies", "fix_commit": "a654aea"},
                           {"run_id": "a4ef3d8a-y", "match_id": "m1", "step": "silver_soda_silver", "what": "old one",
                            "fix_commit": "0d3c37a"}]}
    out = quality.caught(runs, evidence)
    assert [(c["run"], c["stopped_at"], c["not_built"], c["fix"]) for c in out] == [
        ("18bf663e", "silver", "gold", "a654aea"), ("a4ef3d8a", "silver_soda_silver", "", "0d3c37a")]


def test_the_external_checks_name_a_linked_source_for_every_value():
    ext = yaml.safe_load((ROOT / "docs" / "external_checks.yml").read_text(encoding="utf-8"))
    assert all(s["url"].startswith("https://") for s in ext["sources"].values())
    goals = [g for m in ext["matches"].values() for g in m["goals"]]
    assert len(goals) == 15 and all(g["sources"] and set(g["sources"]) <= set(ext["sources"]) for g in goals)
    assert all(0 < v < 1 for m in ext["matches"].values() for v in m["possession"]["sources"].values())


def test_quality_page_shows_the_verdict_the_six_dimensions_and_every_check(app_env, monkeypatch, tmp_path):
    quality_dir = tmp_path / "quality"
    quality_dir.mkdir()
    (quality_dir / "silver_m1.json").write_text(json.dumps({
        "prepared_rows": {"tracking": 13, "ball": 3}, "silver_rows": {"tracking": 13, "ball": 3},
        "replay_copies_removed": {"tracking": 13, "ball": 3}, "positions_corrected": 0, "speeds_rejected": 0,
        "tracking_rows": 13}))
    monkeypatch.setenv("QUALITY_OUT_DIR", str(quality_dir))
    monkeypatch.setenv("PIPELINE_OUT_DIR", str(tmp_path))
    monkeypatch.setenv("QUALITY_EVIDENCE", str(tmp_path / "none.yml"))
    at = AppTest.from_file(str(APP / "sections/data_quality.py"), default_timeout=90).run()
    assert not at.exception
    html = " ".join(m.value for m in at.markdown)
    assert "1 of 3 checks failed" in html                                   # the fixture has one failed check
    for name in ("Completeness", "Uniqueness", "Validity", "Consistency", "Accuracy", "Freshness", "Complétude",
                 "Fraîcheur"):
        assert name in html
    assert [s.value for s in at.subheader] == ["Each match, each dimension", "Caught by our checks"]
    checks = at.dataframe[-1].value
    assert len(checks) == 3 and "2 failing row(s)" in " ".join(checks.detail)
