"""The sentences of the Match story: built from Gold numbers, differences never told as causes."""

import pandas as pd
import pytest

import story

SHORT = {"HOME": "Reds", "AWAY": "Blues"}


def profile(**over) -> pd.DataFrame:
    base = {
        "possession_share": (0.6, 0.4),
        "field_tilt": (0.7, 0.3),
        "shots_and_goals": (10, 9),
        "progressive_passes": (100, 50),
        "ppp": (1.0, 1.1),
        "dpm_outfield": (120.0, 121.0),
    }
    base |= over
    rows = []
    for i, team in enumerate(("HOME", "AWAY")):
        row = {"team_id": team, **{m: v[i] for m, v in base.items()}}
        for m, (h, a) in base.items():
            mine, theirs = (h, a) if team == "HOME" else (a, h)
            row[f"gap_{m}"] = (mine - theirs) / ((mine + theirs) / 2) if mine + theirs else None
        rows.append(row)
    return pd.DataFrame(rows)


def timeline(xt_home, xt_away, poss_home, greyed) -> pd.DataFrame:
    rows = []
    for w, (xh, xa, ph, g) in enumerate(zip(xt_home, xt_away, poss_home, greyed, strict=True)):
        label = f"{5 * w}-{5 * w + 5}"
        rows.append(
            {
                "window_index": w,
                "window_label": label,
                "team_id": "HOME",
                "xthreat_successful_passes": xh,
                "possession_share": ph,
                "possession_greyed": g,
            }
        )
        rows.append(
            {
                "window_index": w,
                "window_label": label,
                "team_id": "AWAY",
                "xthreat_successful_passes": xa,
                "possession_share": 1 - ph,
                "possession_greyed": g,
            }
        )
    return pd.DataFrame(rows)


def test_key_differences_are_the_three_largest_gaps_and_say_had_more():
    out = story.key_differences(profile(), SHORT)
    # gaps: field tilt 0.4 / 0.5 = 0.8, progressive passes 50 / 75 = 0.67, possession 0.2 / 0.5 = 0.4
    assert [s.facts["metric"] for s in out] == ["field_tilt", "progressive_passes", "possession_share"]
    assert out[1].text == "Reds made more passes of 10 m or more toward goal: 100, against 50 for Blues."
    assert out[2].text == "Reds had more of the ball: 60%, against 40% for Blues."
    for s in out:
        assert "because" not in s.text and "won" not in s.text


def test_the_team_with_more_comes_first_even_when_it_is_away():
    out = story.key_differences(profile(ppp=(0.5, 1.5)), SHORT, n=1)
    assert out[0].text.startswith("Blues pressed more: 1.50")


def test_momentum_counts_the_spells_and_names_the_strongest():
    s = story.momentum(timeline([0.1, 0.0, 0.5], [0.2, 0.1, 0.0], [0.5, 0.5, 0.5], [False] * 3), SHORT)
    assert s.text == (
        "Blues created more danger with its passes in 2 of the 3 five-minute spells; its strongest spell "
        "was minutes 0-5."
    )  # -0.1 in spells 0 and 1: the first is named
    assert (s.facts["home_ahead"], s.facts["away_ahead"]) == (1, 2)


def test_possession_skips_greyed_spells_and_says_how_many():
    s = story.possession(
        timeline([0] * 3, [0] * 3, [0.9, 0.6, 0.7], [True, False, False]), profile(possession_share=(0.65, 0.35)), SHORT
    )
    assert s.text == (
        "Reds had the ball 65% of the time; its best spell was minutes 10-15 with 70%. "
        "1 spell is greyed: under 60 seconds with a known owner."
    )


def test_goals_and_plurals():
    shots = pd.DataFrame(
        {
            "is_goal": [True, False, True],
            "ts": [60, 100, 3000],
            "period": [1, 1, 2],
            "event_id": ["e1", "e2", "e3"],
            "team_id": ["HOME", "HOME", "AWAY"],
            "player_short_name": ["A", "B", "C"],
            "distance_to_goal_m": [10.0, 20.0, 12.0],
        }
    )
    # second half from ts 2900: ts 3000 is 1:40 into it, the 47th minute
    assert story.goals(shots, SHORT, (1, 1), (0, 2900)).text == (
        "2 goals. Reds scored first (minute 2), Blues scored the last one (minute 47): final score 1-1."
    )
    assert story.shots_line(shots, SHORT).text == (
        "Reds shot 2 times (1 goal) from 15 m on average; Blues shot 1 time (1 goal) from 12 m on average."
    )


@pytest.mark.parametrize(
    "hubs, expected",
    [
        (
            [True, False],
            "A was the hub of Reds, the player most involved in its successful passes: 1 pass made and 4 received.",
        ),
        ([True, True], "A and B shared the hub role of Reds: equally involved in its successful passes."),
    ],
)
def test_hub_sentence(hubs, expected):
    card = pd.DataFrame(
        {
            "team_id": "HOME",
            "is_hub": hubs,
            "short_name": ["A", "B"],
            "player_id": ["H1", "H2"],
            "passes_successful": [1, 2],
            "passes_received_successful": [4, 3],
            "involvement": [0.5, 0.5],
        }
    )
    assert story.hub(card, "HOME", SHORT).text == expected


def test_compare_names_the_venue_and_puts_the_largest_changes_first():
    import coach

    rows = pd.DataFrame(
        {
            "match_id": ["m2", "m3"],
            "possession_share": [0.63, 0.50],
            "field_tilt": [0.75, 0.40],
            "width": [39.0, 38.0],
            "defensive_line_height": [37.7, 33.0],
            "ppp": [1.10, 1.00],
            "progressive_passes_per90": [178.0, 120.0],
            "dpm_outfield": [123.0, 125.0],
        }
    )
    labels = {"m2": "at home against Perth Glory (0-1)", "m3": "away at Perth Glory (3-1)"}
    out = coach.compare(rows, labels, "Brisbane Roar")
    assert [s.facts["metric"] for s in out] == ["field_tilt", "progressive_passes_per90", "possession_share"]
    assert out[2].text == (
        "At home against Perth Glory (0-1), Brisbane Roar had 63% of the ball; away at Perth Glory (3-1), 50%."
    )
