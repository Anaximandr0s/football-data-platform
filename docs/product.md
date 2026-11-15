# MatchLens: product definition

MatchLens is a match analysis app built on tracking and event data. It serves two kinds of users with the same Gold
tables: fans, who want to understand a match, and coaches of clubs without an analysis team, who want to understand how
a team plays. Brisbane Roar is the demo team: both of our matches (m001, m002) are its home games.

Every number on screen answers one of the questions below. A statistic with no question is not shown.

## 1. What the raw data allows (checked on the SkillCorner files)

**Possession.** Every frame of `tracking_extrapolated.jsonl` has `possession: {player_id, group}`, with group
`home team`, `away team` or null. Sampled at 1 Hz like ingestion does:

| | m001 | m002 |
|---|---|---|
| seconds with a possession group | 3,287 of 6,030 (54.8 min) | 3,560 of 6,130 |
| HOME share of those seconds | 39.6 % | 63.1 % |
| HOME share of passes (cross-check, Gold) | 37.4 % | 63.9 % |
| 5-min windows with fewer than 60 known seconds (greyed out, F2) | 1 of 21: the last, partial window (10 s); the lowest full window has 70 s | 0 of 21 (lowest: 76 s) |

The known-possession time of m001 (54.8 min) equals its ball-in-play time (54.7 min, `docs/data-sources.md`), so a null
group means the ball is dead or nobody controls it. Possession % per team and per 5 minutes is computable. It is not in
our tables today: ingestion has to carry it (section 6).

**Stable player id.** `match.json` gives each player a SkillCorner `id` (plus `team_player_id`). 13 Brisbane Roar
players appear in both matches with the same `id`, name and shirt number, and no player has the same name and team
under two ids. Our `player_id` (`H01`, `A07`...) is local to a match, so linking needs the source id carried into
`players` (section 6).

**Detected or extrapolated.** Each player position has `is_detected`. In m001 only 57.9 % of the player-seconds are
detected by the camera; the rest are estimated by SkillCorner. Ingestion drops this flag today; it is carried with the
possession change (section 6).

## 2. Shared definitions

| Name | Definition |
|---|---|
| Frame | Silver frame: pitch 105 x 68 m, HOME attacks toward x = 105, AWAY toward x = 0 (tracking, ball and events) |
| `x_att` | distance from the team's own goal line toward the goal it attacks: `x` for HOME, `105 - x` for AWAY |
| `y_att` | `y` for HOME, `68 - y` for AWAY. Seen by the attacking team: `y_att > 45.33` is its left, `< 22.67` its right |
| Thirds | own third `x_att < 35`, middle `35 <= x_att < 70`, final third `x_att >= 70` |
| `w5`, `w15` | 5- and 15-minute windows of the match clock: `ts // 300`, `ts // 900` |
| Outfield | `silver.players.position != 'GK'` |
| Tracked minutes | `count(*) / 60` of the player's (or team's) rows in `silver.tracking` |
| `dpm` | distance per tracked minute = `sum(speed_kmh / 3.6) / (count(speed_kmh) / 60)` (null speeds count in neither part) |
| Opponent | the other team of the same match |
| Progressive pass | `type = 'pass'` and `x_att(x_end) - x_att(x_start) >= 10` |
| Defensive action | `type in ('pressure', 'tackle', 'foul')`: the whole engagement family of the source (tackles and fouls are carved out of it at ingestion) |
| Possession second | a second of `silver.ball` whose `possession` is the team (column to add, section 6) |

## 3. Persona 1: fans

People who love football but do not read statistics. They want to know what happened, who played well and why their
team won or lost. Every metric has one plain sentence under it, numbers are rounded, and players are shown as cards.

| # | Question | Metric | Formula (Silver / Gold) | Page | When |
|---|---|---|---|---|---|
| F1 | How did the match go, minute by minute? | Match story: field tilt per 5 min, with goals marked | `field_tilt(T, w5) = passes of T with x_att(x_start) >= 70 / same count for both teams`, from `silver.events`; goals from `gold_shots.is_goal` and `score_*_after` | Match story | post |
| F2 | Who had the ball? | Possession % per team and per 5 min | `possession_seconds(T, w5) / (possession_seconds(HOME, w5) + possession_seconds(AWAY, w5))`; match total over all seconds. A window with under 60 known seconds is greyed out | Match story, Live | live (per 5 min) + post |
| F3 | Who played well? | Player card: 5 scores ranked within the match (section 3.1) | `gold_player_card` | Player cards | post |
| F4 | Who worked the hardest? | Distance per tracked minute | `dpm` per player from `silver.tracking` | Player cards, Live | live (per 5 min) + post |
| F5 | Who was the fastest? | Top speed (approximate) | `max(speed_kmh)` per player, shown as "about N km/h" | Player cards, Live | live (per 5 min) + post |
| F6 | Who made the team play? | Pass network hub | `involvement(p) = (successful passes made by p + successful passes received by p) / (2 x successful passes of the team)`; hub = player with the highest `involvement` in their team | Passing | post |
| F7 | Why did we win or lose? | Three biggest differences between the teams | for each team metric `m` in {possession %, field tilt, shots + goals, progressive passes, defensive actions per opponent pass, dpm of outfield players}: `gap = (m_T - m_O) / ((m_T + m_O) / 2)`; show the 3 largest `abs(gap)` as sentences ("Brisbane had 63 % of the ball") | Match story | post |
| F8 | How is my player doing across matches? | The player's card in each match, side by side | `gold_player_card` rows sharing one `source_player_id`, one column per match; scores stay ranked within their own match, and each column names the opponent | Player cards | post |

F7 states differences, not causes: the sentences say "had more", never "won because". F8 compares ranks, not raw
values: a score of 80 means "better than 80 % of the eligible players of that match", and the opponent differs.

### 3.1 Player card

Eligible players: outfield, at least 20 tracked minutes. Each score is
`round(100 * percent_rank() over (partition by match_id order by metric))` among eligible players of both teams, so 100
means best in this match.

| Score | Metric |
|---|---|
| Work rate | `dpm` |
| Sprints | sprint efforts (`gold_player_match_stats.sprint_count`) per tracked minute |
| Passing | successful passes per tracked minute |
| Progression | successful progressive passes per tracked minute |
| Defending | defensive actions per tracked minute |

Goals, top speed and the hub badge are shown on the card but are not scores (goals are too rare to rank). Goalkeepers
get a card without scores.

## 4. Persona 2: coaches and analysts of small clubs

Clubs without a large analysis team. They want to see how a team plays: shape, pressing, build-up, fatigue, strengths
and weaknesses, and how one match compares with another.

| # | Question | Metric | Formula (Silver / Gold) | Page | When |
|---|---|---|---|---|---|
| C1 | What shape does the team take, with and without the ball? | Width, length, compactness | per tracked second `s` and team T, over outfield players: `width = max(y) - min(y)`, `length = max(x_att) - min(x_att)`, `area = width x length` (smaller = more compact); then the mean over seconds, split by phase (T in possession / opponent in possession / unknown). Live: the current second only, computed in the page from the Kafka positions | Team shape, Live | live (current second) + post |
| C2 | How high does the team defend? | Defensive line height | per second: mean `x_att` of the 4 outfield players with the smallest `x_att` (assumes a back four); mean over seconds when the opponent has the ball | Team shape | post |
| C3 | How hard and where does the team press? | Defensive actions per opponent pass per 15 min; pressing zones | `ppp(T, w15) = defensive actions of T in w15 / passes of the opponent in w15` (higher = more intense); zones: share of T's defensive actions by third of `x_att(x_start)`, `high_press_share` = final third. Live: the same ratio per 5-min window | Pressing, Live (ppp) | live (per 5 min) + post |
| C4 | How does the team move the ball forward? | Progressive passes | count, successful count and success rate of progressive passes per team and per player; per tracked minute for comparison | Build-up and attack | post |
| C5 | Which side does the team attack? | Attack side | successful passes of T ending in the final third (`x_att(x_end) >= 70`), by lane of `y_att(y_end)`: left `> 45.33`, centre, right `< 22.67`; shares of the three lanes | Build-up and attack | post |
| C6 | Who is getting tired? | Fatigue | per outfield player with at least 30 minutes on the pitch: `dpm` in their first 15 minutes on the pitch (`start_ts <= ts < start_ts + 900`) vs their last 5 (`end_ts - 300 < ts <= end_ts`); `drop = 1 - dpm_last5 / dpm_first15`. Shown only with at least 5 tracked minutes in the first window and 2 in the last | Fatigue | post |
| C7 | Is this how the team usually plays? | Team profile m001 vs m002 | one row per match and team with: possession %, field tilt, width, length, defensive line height, `ppp`, `high_press_share`, progressive passes and `dpm` per tracked minute, attack side shares; shown side by side for the same team (Brisbane Roar in both matches) | Compare matches | post |

C6 is a signal for the bench, not a diagnosis: the last minutes also contain stoppages and changes in game state.

Effect of counting defensive actions instead of pressures only (m001, whole match, measured on Gold):

| Team | Pressures | Defensive actions | Opponent passes | `ppp` pressures only | `ppp` defensive actions | `high_press_share` before | after |
|---|---|---|---|---|---|---|---|
| HOME | 482 | 503 | 524 | 0.920 | 0.960 | 17.6 % | 17.1 % |
| AWAY | 353 | 375 | 313 | 1.128 | 1.198 | 18.7 % | 18.4 % |

The 36 tackles and 7 fouls raise `ppp` by 4.3 % (HOME) and 6.2 % (AWAY) and leave the ranking and the zones almost unchanged.

## 5. Rules for every number

- **Divide by tracked minutes.** About a quarter of each match has no tracking. Totals are shown, but comparisons use
  per-tracked-minute values. Events follow the same rule: 99.4 % of them fall in tracked seconds (11 of 1,741 in m001,
  11 of 1,878 in m002, measured).
- **Compare within a match.** Ranks and scores are computed inside one match. Across matches only team profiles are
  compared, with the opponent named next to them.
- **1 Hz speeds are approximate.** Speeds come from positions one second apart: top speeds are written "about N km/h"
  and they under-estimate short peaks.
- **No xG.** The source has no shot outcome (on target, saved, blocked), so there is no expected-goals model. Shots,
  shot distance and goals are shown as they are.
- **Small samples are greyed out**, not hidden: thresholds are written next to each metric (20 tracked minutes for a
  card, 60 known seconds for a possession window, the fatigue thresholds of C6).
- **Shape uses estimated positions.** 42 % of m001's player positions are extrapolated by SkillCorner, not seen by the
  camera. The shape pages show the detected share of the positions they use.

## 6. Changes needed before Gold

These touch ingestion and the data contract (`docs/contrat_donnees.md`), so they come first:

1. `possession` (`HOME` / `AWAY` / null) per second, added to the `ball` table: ingestion, Kafka message, Bronze schema,
   Silver, Soda schema check. Needed by F2, F7, C1, C2, C7.
2. `source_player_id` (SkillCorner `id`) in `players`, carried to `silver.players` and `gold_player_match_stats`. Needed
   to follow a player across matches.
3. `is_detected` in `tracking`, in the same change: the shape pages show the detected share of the positions they use.

## 7. New Gold tables (proposal)

| Table | Grain | Content | Answers |
|---|---|---|---|
| `gold_match_timeline` | match x team x 5-min window | passes, final-third passes, field tilt, possession seconds and share, known seconds, shots, goals, score at window end, defensive actions | F1, F2, F7 |
| `gold_player_card` | match x player | `source_player_id`, eligibility, `dpm`, top speed, sprint efforts, passes, progressive passes, defensive actions (all per tracked minute), 5 scores, `involvement`, `is_hub` | F3, F4, F5, F6, F8 |
| `gold_team_shape` | match x team x phase | width, length, area, defensive line height, seconds used, detected share of the positions. Built from an intermediate model `int_team_shape_second` (match x team x second) | C1, C2 |
| `gold_pressing` | match x team x 15-min window | defensive actions, opponent passes, `ppp`, defensive actions by third, `high_press_share` | C3 |
| `gold_team_build_up` | match x team | progressive passes (count, successful, rate, per tracked minute), final-third entries and shares by lane | C4, C5 |
| `gold_player_fatigue` | match x player | `dpm_first15`, `dpm_last5`, `drop`, tracked minutes in each window, eligibility | C6 |
| `gold_team_profile` | match x team | one wide row joining the team metrics above, plus the F7 gaps | C7, F7 |

Live scope. Spark Structured Streaming (FOO-08) reads Kafka and computes only F2, F4, F5 and C3, per 5-min window, with
the formulas of this document. C1 on the live page is the current second only, computed in the page from the Kafka
positions, without Spark. F1, C6 and every other question are post-match only, read from the Gold tables above.

## 8. Why someone would pay

**Fans, through clubs and media.** Clubs and broadcasters need content that keeps fans watching during and after a
match. MatchLens turns tracking data into a live second screen and shareable player cards written in plain language,
which a club can put in its app or a media site can embed.

**Coaches of small clubs.** Shape, pressing, build-up and fatigue analysis usually needs a dedicated analyst and
specialist software. MatchLens gives those answers from the tracking data the league already collects, with each number
explained and its limits stated, so one coach can prepare the next match without an analysis department.
