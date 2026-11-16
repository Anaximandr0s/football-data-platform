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
| 5-min windows with fewer than 60 known seconds (greyed out, F2) | 0 of 20 football windows (lowest: 45+, 68 s in a 191 s window); with the old `ts // 300` windows, 1 of 21 (the last, 10 s) | 0 of 20 |

The known-possession time of m001 (54.8 min) equals its ball-in-play time (54.7 min, `docs/data-sources.md`), so a null
group means the ball is dead or nobody controls it. Possession % per team and per 5 minutes is computable. It is not in
our tables today: ingestion has to carry it (section 6).

**Stable player id.** `match.json` gives each player a SkillCorner `id` (plus `team_player_id`). 13 Brisbane Roar
players are in both squads with the same `id`, name and shirt number, and no player has the same name and team under
two ids. 11 of them played both matches (Acton and Zabala were unused substitutes twice), and only players who played
are in `players`: F8 has 11 players to follow. Our `player_id` (`H01`, `A07`...) is local to a match, so linking needs the source id carried into
`players` (section 6).

**Detected or extrapolated.** Each player position has `is_detected`. In m001 only 57.9 % of the player-seconds are
detected by the camera; the rest are estimated by SkillCorner. Ingestion drops this flag today; it is carried with the
possession change (section 6).

**Event columns we drop.** `dynamic_events.csv` has 322 columns and four row families: player possessions (959 rows in
m001, 1,054 in m002), on-ball engagements (878, 936), off-ball runs (535, 498) and passing options (2,543, 2,734).
Ingestion keeps possessions ending in a pass or a shot and the engagements, with 11 columns. Fill rates of the columns
that matter for the replay and the event explorer, on the rows where the column applies (m001 / m002):

| Column | Rows | Fill | What it holds |
|---|---|---|---|
| `player_targeted_xthreat` | passes (837 / 912) | 95.3 % / 95.6 % | SkillCorner xThreat of the option the pass aimed at |
| `player_targeted_dangerous` | passes | 95.3 % / 95.6 % | that option was dangerous (boolean) |
| `xthreat`, `dangerous` | runs, passing options | 100 % | xThreat and danger of the run or the option |
| `team_in_possession_phase_type` | every row | 100 % | build_up, create, finish, direct, quick_break, transition, set_play, chaotic, disruption |
| `team_out_of_possession_phase_type` | every row | 100 % | high_block, medium_block, low_block and their defending_* twins |
| `speed_avg_band` | possessions / engagements / runs | 97 % / 99 % / 99 % (m002: 95 / 99 / 99) | jogging, running, hsr, sprinting |
| `event_subtype` | engagements, runs | 100 % | engagements: pressure, recovery_press, pressing, counter_press, other; runs: run_ahead_of_the_ball, support, coming_short, behind, dropping_off, pulling_wide, cross_receiver, overlap, underlap, pulling_half_space |
| `targeted`, `received` | runs, options | 100 % | the run or option got the pass, and received it (m001 runs: 188 targeted, 132 received) |
| `lead_to_shot`, `lead_to_goal` | every row | 100 % | the possession ended in a shot or goal |
| `break_defensive_line` | runs | 8 % / 3 % | only set when the run broke a line |
| `n_passing_options` | possessions | 100 % | options available to the player on the ball |

xThreat sits on runs and options, not on possessions: a pass carries the value of its targeted option. 203 of m001's
535 runs (137 of 498 in m002) are flagged dangerous.

**Phases of play.** SkillCorner publishes `<id>_phases_of_play.csv` for both matches (checked in the repository, not
downloaded by `download_foot.py` today): 423 phases in m001 and 483 in m002, 44 columns, every column at least 95.7 %
filled. Each phase has its team, type (in and out of possession), start and end frame and location, whether it led to a
shot or goal, and the width and length of both teams at its start and end. Together the phases cover 54.6 min of m001
and 59.5 min of m002, the ball-in-play time.

## 2. Shared definitions

| Name | Definition |
|---|---|
| Frame | Silver frame: pitch 105 x 68 m, HOME attacks toward x = 105, AWAY toward x = 0 (tracking, ball and events) |
| `x_att` | distance from the team's own goal line toward the goal it attacks: `x` for HOME, `105 - x` for AWAY |
| `y_att` | `y` for HOME, `68 - y` for AWAY. Seen by the attacking team: `y_att > 45.33` is its left, `< 22.67` its right |
| Thirds | own third `x_att < 35`, middle `35 <= x_att < 70`, final third `x_att >= 70` |
| `w5`, `w15` | 5- and 15-minute football windows: they restart at each kick-off, on the football clock. 5 minutes: 0-5' ... 40-45', 45+ (first-half stoppage time, as long as it lasted), 45-50' ... 85-90', 90+. 15 minutes: 0-15', 15-30', 30-45', 45+, 45-60', 60-75', 75-90', 90+. One definition: `clock.window_index` (Python, also for Spark Streaming in step 6) and the dbt macro `football_window`, checked equal by a test. A short window keeps its own length for coverage and is greyed by the usual thresholds |
| Outfield | `silver.players.position != 'GK'` |
| Tracked minutes | player: `count(*) / 60` of the player's rows in `silver.tracking`; team: its distinct tracked seconds / 60 (not the sum of its players' minutes) |
| Team rate | a team count per 90 tracked minutes: `count / team tracked minutes x 90` |
| `dpm` | distance per tracked minute = `sum(speed_kmh / 3.6) / (count(speed_kmh) / 60)` (null speeds count in neither part). Label: "per minute of tracked play (mostly ball in play)": the camera loses the play mostly when the ball is dead, so tracked time is richer in running than the whole match (m001 outfield: 148 m/min while a team owns the ball, 85 when nobody does, 131 overall) |
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
| F5 | Who was the fastest? | Top speed (approximate) | `max(speed_kmh)` per player over the speeds whose two positions (this second and the one before) are both detected, shown as "about N km/h" | Player cards, Live | live (per 5 min) + post |
| F6 | Who made the team play? | Pass network hub | `involvement(p) = (successful passes made by p + successful passes received by p) / (2 x successful passes of the team)`; hub = player with the highest `involvement` in their team | Passing | post |
| F7 | Why did we win or lose? | Three biggest differences between the teams | for each team metric `m` in {possession %, field tilt, shots + goals, progressive passes, defensive actions per opponent pass, dpm of outfield players}: `gap = (m_T - m_O) / ((m_T + m_O) / 2)`; show the 3 largest `abs(gap)` as sentences ("Brisbane had 63 % of the ball") | Match story | post |
| F8 | How is my player doing across matches? | The player's card in each match, side by side | `gold_player_card` rows sharing one `source_player_id` (11 Brisbane Roar players in m001 and m002), one column per match; scores stay ranked within their own match, and each column names the opponent | Player cards | post |

F5 uses detected positions only because a speed joins two positions one second apart, and every speed above 33 km/h
in m001 and m002 (up to 39.2 km/h) had an estimated position at one end; with both ends detected the fastest second is
33.0 km/h in m001 and 31.7 km/h in m002. The other Gold tables keep `max_speed_kmh` over all positions.

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
| C1 | What shape does the team take, with and without the ball? | Width, length, compactness | per tracked second `s` and team T, over outfield players: `width = max(y) - min(y)`, `length = max(x_att) - min(x_att)` (label: "outfield block length"), `area = width x length` (smaller = more compact); then the mean over seconds, split by phase (T in possession / opponent in possession / unknown). Live: the current second only, computed in the page from the Kafka positions | Team shape, Live | live (current second) + post |
| C2 | How high does the team defend? | Defensive line height | per second: mean `x_att` of the 4 outfield players with the smallest `x_att` (assumes a back four); mean over seconds when the opponent has the ball | Team shape | post |
| C3 | How hard and where does the team press? | Defensive actions per opponent pass per 15 min; pressing zones | `ppp(T, w15) = defensive actions of T in w15 / passes of the opponent in w15` (higher = more intense); a window where the opponent made fewer than 10 passes is greyed out (a short stoppage window can reach 2.6 on a handful of passes); zones: share of T's defensive actions by third of `x_att(x_start)`, `high_press_share` = final third. Live: the same ratio per 5-min window | Pressing, Live (ppp) | live (per 5 min) + post |
| C4 | How does the team move the ball forward? | Progressive passes | count and successful count of progressive passes per team and per player; per 90 tracked minutes for comparison (team rate). No success rate (see below) | Build-up and attack | post |
| C5 | Which side does the team attack? | Attack side | successful passes of T ending in the final third (`x_att(x_end) >= 70`), by lane of `y_att(y_end)`: left `> 45.33`, centre, right `< 22.67`; shares of the three lanes | Build-up and attack | post |
| C6 | Who is getting tired? | Fatigue | per outfield player with at least 30 minutes on the pitch: `dpm` in their first 15 minutes on the pitch (`start_ts <= ts < start_ts + 900`) vs their last 5 (`end_ts - 300 < ts <= end_ts`); `drop = 1 - dpm_last5 / dpm_first15`. Shown only with at least 5 tracked minutes in the first window and 2 in the last | Fatigue | post |
| C7 | Is this how the team usually plays? | Team profile m001 vs m002 | one row per match and team with: possession %, field tilt, width, length, defensive line height, `ppp`, `high_press_share`, progressive passes per 90 tracked minutes, `dpm`, attack side shares; shown side by side for the same team (Brisbane Roar in both matches) | Compare matches | post |

C1 length is the outfield block: SkillCorner's own team length (`phases_of_play.csv`) includes the goalkeeper.
Cross-check on m001, 1,650 phase starts and ends: width matches SkillCorner (median gap 0.24 m); our outfield length is
about 21 m shorter, and the same measure with the goalkeeper added matches SkillCorner (median gap 0.26 m, correlation
0.988). The goalkeeper is left out on purpose: he stretches the length without telling how compact the block is.

C4 has no success rate: a failed pass has no reception point in the source (0 of 137 in m001, 0 of 132 in m002), so its
stored end is the end of the passer's own possession, a median 1.5 m (m001) from where it started. Failed passes then
rarely look progressive (8.8 % in m001, against 27.7 % when measured to where the target stood), and the rate came out
at 89 % to 96 %. Successful progressive passes are reliable (their end is the reception point) and are kept; the total
count misses most failed attempts and is shown as such.

C6 is a signal for the bench, not a diagnosis: the last minutes also contain stoppages and changes in game state.

Effect of counting defensive actions instead of pressures only (m001, whole match, measured on Gold):

| Team | Pressures | Defensive actions | Opponent passes | `ppp` pressures only | `ppp` defensive actions | `high_press_share` before | after |
|---|---|---|---|---|---|---|---|
| HOME | 482 | 503 | 524 | 0.920 | 0.960 | 17.6 % | 17.1 % |
| AWAY | 353 | 375 | 313 | 1.128 | 1.198 | 18.7 % | 18.4 % |

The 36 tackles and 7 fouls raise `ppp` by 4.3 % (HOME) and 6.2 % (AWAY) and leave the ranking and the zones almost unchanged.

## 5. Rules for every number

- **Divide by tracked minutes.** About a quarter of each match has no tracking. Totals are shown, but comparisons use
  per-tracked-minute values. Events follow the same rule: 99.4 % of the actions fall in tracked seconds (11 of 1,741 in m001,
  11 of 1,878 in m002, measured).
- **Compare within a match.** Ranks and scores are computed inside one match. Across matches only team profiles are
  compared, with the opponent named next to them.
- **1 Hz speeds are approximate.** Speeds come from positions one second apart: top speeds are written "about N km/h"
  and they under-estimate short peaks.
- **No xG.** The source has no shot outcome (on target, saved, blocked), so there is no expected-goals model. Shots,
  shot distance and goals are shown as they are.
- **xThreat is SkillCorner's, and it is not xG.** It values the option a pass or run aimed at, before the outcome. It is
  shown as "SkillCorner xThreat" and never summed into expected goals.
- **Small samples are greyed out**, not hidden: thresholds are written next to each metric (20 tracked minutes for a
  card, 60 known seconds for a possession window, 10 opponent passes for a pressing window, the fatigue
  thresholds of C6).
- **Shape uses estimated positions.** 42 % of m001's player positions are extrapolated by SkillCorner, not seen by the
  camera. The shape pages show the detected share of the positions they use.

## 6. Changes needed before Gold

These touch ingestion and the data contract (`docs/contrat_donnees.md`), so they come first:

1. `possession` (`HOME` / `AWAY` / null) per second, added to the `ball` table: ingestion, Kafka message, Bronze schema,
   Silver, Soda schema check. Needed by F2, F7, C1, C2, C7.
2. `source_player_id` (SkillCorner `id`) in `players`, carried to `silver.players` and `gold_player_match_stats`. Needed
   to follow a player across matches.
3. `is_detected` in `tracking`, in the same change: the shape pages show the detected share of the positions they use.

Proposed for the same change, because the replay and the event explorer need them and they stay inside the existing
`events` table and topic:

4. New columns on the existing event rows: `phase` (in possession) and `phase_against` (out of possession), `xthreat` and
   `dangerous` (on passes, from the targeted option), `speed_band`, `subtype` (engagements), `lead_to_shot`.
5. Off-ball runs as a new event type `run` (535 rows in m001, 498 in m002), with `subtype`, `targeted`, `received`,
   `dangerous`, `xthreat` and `speed_band`. The Soda check on accepted types, the manifest counts and the Gold models
   that count events by type are updated with it.

Proposed for a later change:

6. `phases_of_play.csv` as a sixth table: a new file to download, a new topic and a new Silver table. It is needed only
   to split shape and space control by phase type per second; the explorer's phase filter works with item 4.
7. Passing-option rows (2,543 and 2,734 per match): five times the events volume, for a view of the options around each
   possession that no page in section 8 needs yet.

Not proposed: EPV, xLoss and xShot. They are model outputs no question uses.

## 7. New Gold tables (proposal)

| Table | Grain | Content | Answers |
|---|---|---|---|
| `gold_match_timeline` | match x team x 5-min window | passes, final-third passes, field tilt, possession seconds and share, known seconds, shots, goals, score at window end, defensive actions | F1, F2, F7 |
| `gold_player_card` | match x player | `source_player_id`, eligibility, `dpm`, top speed, sprint efforts, passes, progressive passes, defensive actions (all per tracked minute), 5 scores, `involvement`, `is_hub` | F3, F4, F5, F6, F8 |
| `gold_team_shape` | match x team x phase | width, length, area, defensive line height, seconds used, detected share of the positions. Built from an intermediate model `int_team_shape_second` (match x team x second) | C1, C2 |
| `gold_pressing` | match x team x 15-min window | defensive actions, opponent passes, `ppp`, defensive actions by third, `high_press_share` | C3 |
| `gold_team_build_up` | match x team | progressive passes (count, successful, per 90 tracked minutes), final-third entries and shares by lane | C4, C5 |
| `gold_player_fatigue` | match x player | `dpm_first15`, `dpm_last5`, `drop`, tracked minutes in each window, eligibility | C6 |
| `gold_team_profile` | match x team | one wide row joining the team metrics above, plus the F7 gaps | C7, F7 |
| `gold_space_control` | match x team x 5-min window | mean space share over tracked seconds, by phase (in possession / opponent in possession / unknown), seconds used. Built from `int_space_control_second` (match x second: HOME share, AWAY = 1 - HOME) | S1 |
| `gold_replay_frames` | match x second x object (players and ball) | x, y, team, shirt number, `is_detected`, possession, HOME space share of the second | R1, S1 |
| `gold_events` | one row per event, runs included | the Silver event columns plus player names, `x_att`, `y_att`, third and lane, phase, `xthreat`, `dangerous`, `speed_band`, `subtype` | E1, E2 |
| `gold_match_library` | match | teams, colours, score, kick-off date, competition, round, stadium, tracked share | Match library, Home |

`gold_match_timeline` also gets `xthreat_successful_passes` per team and window, the input of E2.

Live scope. Spark Structured Streaming (FOO-08) reads Kafka and computes only F2, F4, F5 and C3, per 5-min window, with
the formulas of this document, and writes them to the Kafka topic `foot-live-stats`, which the Live match page reads (no
other service is added). C1 on the live page is the current second only, computed in the page from the Kafka
positions, without Spark. F1, C6 and every other question are post-match only, read from the Gold tables above.

## 8. App map

MatchLens is one website (one Streamlit app, `st.navigation` with sections). Home is the door; LIVE and MATCHES serve
both personas; FAN VIEW and COACH VIEW answer the questions of sections 3 and 4 for the match chosen on Home;
BEHIND THE DATA is for the jury. The ids point to sections 3, 4 and 8.1; FOO-xx are the requirements of the brief.

| Section | Page | Question it answers | Persona | Source | Metric ids |
|---|---|---|---|---|---|
| | Home | Who am I, and which match do I look at? | both | MatchLens logo, "I am a Fan / I am a Coach" (opens FAN VIEW or COACH VIEW), match picked from the Match library | |
| LIVE | Live match | What is happening right now, and how is this player doing so far? | both | Kafka topics `foot-tracking`, `foot-ball`, `foot-events`, `foot-players`, `foot-matches`; `foot-live-stats` written by Spark Streaming | pitch, score, clock, possession (F2 now), C1 (current second); click a player: distance, top speed, sprints and heatmap so far (F4, F5, FOO-07); per 5 min: F2, F4, F5, C3 (FOO-08) |
| MATCHES | Match library | Which matches are stored, and how did they end? | both | `gold_match_library` | |
| MATCHES | Replay | What did a stored match look like at any moment? | both | `gold_replay_frames`, `gold_space_control`; the stats panel reads `gold_player_5min`, `gold_match_timeline` up to the replay time | R1, S1; panel: the same as Live (F4, F5, sprints, heatmap so far, F2, C3 per 5 min) |
| MATCHES | Compare matches | Is this how a team usually plays? (any matches) | both | `gold_team_profile` | C7, F7 gaps |
| FAN VIEW | Match story | How did the match go, and why did it end this way? | fans | `gold_match_timeline`, `gold_shots`, `gold_team_profile` | F1 (goals on the timeline), E2 (momentum), F2, F7 (3 key differences) |
| FAN VIEW | Squad | Who played? | fans | `gold_player_card` | players as cards: shirt colour, number, name; click -> Player page |
| FAN VIEW | Player page | How did this player play? | fans | `gold_player_card`, `gold_zone_occupancy`, `gold_shots`, `gold_events` (passes) | F3 (5 scores), F4, F5 (top speed), F6 (hub badge), F8 (across matches), FOO-07 (heatmap, shots) |
| COACH VIEW | Team analysis | How does the team organise, press and attack? | coaches | `gold_team_shape`, `gold_pressing`, `gold_team_build_up`, `gold_space_control`, `gold_shots`, `gold_pass_network` | C1, C2 (shape), C3 (pressing), C4 (build-up), C5 (attack side), S1 by phase, F6 (pass network) |
| COACH VIEW | Physical & fatigue | Who ran how much, and who faded? | coaches | `gold_player_5min`, `gold_player_fatigue` | F4 per 5 min, C6 |
| COACH VIEW | Event explorer | Which actions happened where, by whom, and how dangerous were they? | coaches | `gold_events`, `gold_match_timeline` | E1, E2 |
| COACH VIEW | Player page (detailed) | What exactly did this player do? | coaches | the fan sources plus `gold_player_fatigue`, `gold_player_5min`, `gold_events` | F3 with raw values and per-minute rates and the eligibility thresholds, C6, F4 per 5 min, E1 for this player |
| BEHIND THE DATA | Data quality | Can I trust these numbers? | jury | `data/soda/*.json`; tracked and detected share per match from `gold_space_control` | FOO-05 |
| BEHIND THE DATA | Pipeline & lineage | How does a number get from the camera to the screen? | jury | dbt docs (`dbt docs generate`: lineage of every Gold table) and the Dagster asset graph | |
| BEHIND THE DATA | Sources & limits | Where does the data come from, and what can it not tell? | jury | sections 1 and 5 of this document, `contrat_donnees.md` known characteristics, credits | |

The Player page is one page in two modes: the fan mode shows the card and the pitch layers; the coach mode adds the raw
values, rates, thresholds, fatigue and the player's events. Both views reach it from a click on a player (Squad, Live,
Replay, Team analysis).

### 8.1 Questions added with the replay and the explorer

| # | Question | Metric | Formula | Page | When |
|---|---|---|---|---|---|
| R1 | What did the match look like at minute X? | Replay of the 1 Hz positions | `gold_replay_frames` played at 0.25x to 8x, with play/pause, trails (last N seconds), shirt labels, one highlighted player (click), Voronoi cells, and a toggle that greys out the positions with `is_detected = false` | Replay | post |
| S1 | Which team controlled more of the pitch, and when? | Space control | per tracked second: a 1 m grid over the pitch (105 x 68 = 7,140 cell centres), each cell owned by the nearest of the 22 players; `space(T, s) = cells owned by T / 7,140`. Then the mean over the tracked seconds of each 5-min window, split by phase | Replay, Team analysis | post |
| E1 | Which actions happened where, by whom? | Filtered events | `gold_events` filtered by team, player, type (runs included), phase, period and time range; shown as arrows (start to end), a heatmap of start points or average positions, with a summary table (count, success rate, mean xThreat) and a head-to-head of two players on the same filters | Event explorer | post |
| E2 | Which team was on top, minute by minute? | Momentum | `momentum(w5) = xthreat_successful_passes(HOME, w5) - xthreat_successful_passes(AWAY, w5)`, the sum of `xthreat` over successful passes; passes without a value (about 5 %) add nothing | Match story, Event explorer | post |

Space control uses all 22 positions, detected or not: leaving out the estimated ones would give their cells to the
wrong team. The detected share is shown next to it. The 1 m grid is an approximation of the exact Voronoi areas; it
needs only numpy (already installed with pandas) instead of a geometry library. Its run time is measured when it is
built: above about 60 s per match, the grid becomes 2 m (1,785 cells). The replay draws exact Voronoi cells
for the eye, but every number it shows comes from `gold_replay_frames`, so the replay and the Gold tables agree.

### 8.2 One pitch component

Rule: one pitch component, reused by Live, Replay and the Player page, with clickable players.

Technology (approved): a **Streamlit custom component v2** (`st.components.v2.component`,
available in our Streamlit 1.67): our own HTML, CSS and JavaScript passed as strings, drawn on a `<canvas>`, no npm
build, libraries vendored as files in `app/web3d`. It sends a click back to Python (`setTriggerValue("player", id)`),
and it animates in the browser between two data updates. Layers, each switched on by the page: players and ball,
trails, Voronoi cells, heatmap grid, shots, pass arrows, detected-only toggle.

| Option | Click on a player | Moves smoothly | One component for Live, Replay, Player | Verdict |
|---|---|---|---|---|
| Custom component v2 + canvas | yes (tested) | yes, in the browser (tested) | yes | chosen |
| Plotly (`st.plotly_chart`, `on_select="rerun"`) | yes (tested) | no: each move is a Python rerun; Voronoi and trails are heavy (section 9) | Live and Player yes, Replay no | fallback |
| mplsoccer image (today's Live page) | no | no | no | kept for static charts only |
| `st.components.v1.html` (section 9's first choice) | no: one-way | yes | no | replaced |

Both click tests ran on 2026-11-15 in headless Chrome against a throwaway Streamlit 1.67 app (not committed):

- Plotly: a click on the dot of player 9 returned `H09` to Python.
- Component v2: the dot moved from x = 122 to 174, 222 and 270 px in 0.6 s without any Python rerun, and a click on the
  other player returned `A04` to Python.

Its first test, in step 3: a full match (22 players and the ball over m001's 4,428 tracked seconds) inside the 1 s
refresh of the Live page. Result (2026-11-15, 160 s each, headless Chrome on this machine): one frame per refresh, as Live
does, costs 2-3 ms of server time per refresh and stays at 60 frames per second with a flat memory (server 220 MB,
browser heap 11 MB); the whole match (1.9 MB of JSON) sent at every refresh also plays at 60 frames per second without
restarting, but costs about 150 ms of server time per refresh, so Replay sends it once, outside the refresh. What the throwaway test does not show yet: a full match in the component (size and frame rate), the component inside
`st.fragment` refreshes (Live), and a click test that runs in CI (it needs a browser; `streamlit.testing` cannot click
inside a component).

### 8.3 Where the existing pages go, and what is dropped

| Existing page | Goes to |
|---|---|
| Home (`app.py`: average position, team comparison) | Home becomes the door (logo, persona, library); the team comparison becomes F7 in Match story; the average-position chart is dropped (Team analysis shows the shape) |
| Live match | LIVE / Live match: same page, the mplsoccer pitch replaced by the pitch component, plus the player click and the FOO-08 panel |
| Players (key numbers, heatmap, intensity per 5 min, ranking) | key numbers, heatmap and ranking -> Player page and Squad; intensity per 5 min -> Physical & fatigue |
| Shots and passes | team shot map and pass network -> Team analysis; a player's shots and passes -> Player page |
| Compare matches | MATCHES / Compare matches, reading `gold_team_profile` instead of `gold_team_match_stats`, any number of matches |
| Data quality | BEHIND THE DATA / Data quality |

Dropped from the old plan (section 8 before this version): the pages "Player cards" (now Squad + Player page), "Shots &
passes" (split above) and "Team shape & pressing" (now part of Team analysis, with build-up and attack side); "Data
quality reads `gold_replay_frames`" (it reads `gold_space_control`); the one-way `st.components.v1.html` replay
(section 9). No Gold table is dropped: all 15 are read by a page, and
`gold_replay_frames` is still built in the Replay step. Section 6 items 6 and 7 (`phases_of_play` as a table, passing
options) stay out: no page needs them.

Decisions (review of 2026-11-15):

1. **Match library**: a new table `gold_match_library` (one row per match: teams, colours, score, kick-off date,
   competition, round, stadium, tracked share), built in step 2.
2. **Live player stats "so far"** (distance, top speed, sprints, heatmap): computed in the page from the Kafka
   positions, like C1, with the formulas of F4, F5 and FOO-07 (top speed with both positions detected). The formulas
   live in one shared Python module used by the page, with a test that the live values at full time equal Gold. Spark
   computes only the 5-minute windows.
3. **Player page**: one page with a fan mode and a coach mode.
4. **Demo start time**: the producer takes `mm:ss`.

## 9. Smooth replay

| Option | How it plays | Verdict |
|---|---|---|
| Pitch component (custom component v2, canvas, our JavaScript in `app/web3d`) | the page sends the match once; the browser animates, interpolating between seconds, and sends clicks back | chosen (section 8.2) |
| Streamlit HTML component (`st.components.v1.html`) with our JavaScript in `app/web3d` | the same animation, but one-way: a click cannot reach Python, so no stats panel on click | first choice, replaced |
| Streamlit loop redrawing an mplsoccer figure | one server render per frame, no interpolation between seconds | too slow for 0.25x to 8x |
| Plotly animation frames | built-in play button, but every frame and every Voronoi polygon lives in the figure | too heavy with Voronoi and trails |
| Two-way custom Streamlit component (React + npm) | same rendering, plus messages back to Python | a build step we do not need: component v2 does it without one |
| Separate web app on its own port | full freedom, 3D possible | a second server and an API to maintain |

The design: the Replay page reads one match from `gold_replay_frames`, serialises it as compact JSON (positions in
decimetres as integers, one array per second), and passes it to the pitch component. Play/pause, playback speed,
trails, labels, highlight, the Voronoi layer and the detected-only toggle are handled in the browser, so playing never
reruns the Python page; a click on a player sends his id and the replay time to Python, which fills the stats panel.
Voronoi cells come from d3-delaunay, kept as a file in `app/web3d` so the demo works offline. No npm build: every
library is vendored as a file in `app/web3d`. The Replay takes its ideas from SkillCorner's tracking viewer (section
11); the code and the design are ours.

Size, measured on m001 at 1 Hz (4,428 tracked seconds, 32 player slots plus the ball, 101,844 positions): 1.12 MB of
JSON, 0.38 MB gzipped. `is_detected`, possession and the space share add a few columns to that.

The Live match page uses the same component but gets one frame per refresh, so it moves once per second; only the
replay is interpolated.

## 10. Why someone would pay

**Fans, through clubs and media.** Clubs and broadcasters need content that keeps fans watching during and after a
match. MatchLens turns tracking data into a live second screen and shareable player cards written in plain language,
which a club can put in its app or a media site can embed.

**Coaches of small clubs.** Shape, pressing, build-up and fatigue analysis usually needs a dedicated analyst and
specialist software. MatchLens gives those answers from the tracking data the league already collects, with each number
explained and its limits stated, so one coach can prepare the next match without an analysis department.

## 11. Credits

Data: SkillCorner open data (<https://github.com/SkillCorner/opendata>, MIT licence). The Replay and Event
explorer pages take their ideas from SkillCorner's `viz_tools/SkillCorner_Tracking_Viewer.html` and
`viz_tools/Dynamic_Events_Explorer.html` in the same repository: playback speeds, trails, Voronoi and the detected
toggle for the first; filters, arrows, heatmaps, summary table, head-to-head and the xThreat momentum chart for the
second. Our pages use our own code and design; no code is copied from those files.

## 12. Build steps

In this order. Each step is one branch, merged before the next starts; "check" is what you run or look at to accept it.

| # | Step | What you will see | How you check it |
|---|---|---|---|
| 1 | Gold metrics (current, merged) | 15 Gold tables answering sections 3, 4 and 8.1 | `make gold` and `make soda` green; the independent pandas recomputations in `requirements-coverage.md` |
| 2 | Site skeleton | one app with the sections Home, LIVE, MATCHES, FAN VIEW or COACH VIEW (the one chosen), BEHIND THE DATA; existing pages moved to their place (section 8.3), new pages "coming soon" with their question; Home with a text logo, the Fan / Coach choice and a match chooser; the chosen view and match follow you from page to page; `gold_match_library` and the Match library page | headless page tests (`streamlit.testing`): every page renders without error, the chosen match and persona are kept, each page shows its question; you click through every page in a browser |
| 3 | Player pages + pitch component | first, a full match (22 players and the ball, 4,428 s) in the pitch component inside the 1 s Live refresh; then the pitch component (section 8.2) on the Player page with heatmap, shots and passes layers; Squad as cards; a click on a card or a dot opens the Player page, fan or coach mode | Python tests of the data sent to each layer (counts equal Gold); one browser test (Playwright) that clicks a player and checks the page that opens; you click three players |
| 4 | Fan pages | Match story (goals on the timeline, momentum, possession per 5 min with greyed windows, 3 key differences as sentences) and the finished Squad | page tests that read the numbers shown and compare them with Gold; screenshots of m001 and m002 |
| 5 | Coach pages + Compare + 2 matches | Team analysis, Physical & fatigue, Event explorer, Player page coach mode; Compare matches with any matches; the Match library lists 2007448 and 1996435 (2011166 only if time allows) | `make data`, `make replay`, `make silver`, `make gold`, `make soda` green for every match; page tests; Compare shows Brisbane Roar in 3 matches |
| 6 | Spark Streaming (FOO-08) | on Live, the 5-minute panel fills while the replay runs (F2, F4, F5, C3), and the player click shows his live stats so far | the streaming windows of a full replay compared with the batch twins (`gold_player_5min`, `gold_match_timeline`) of the same match, value by value; a test that the live stats so far at full time equal Gold (shared formula module); you watch a replay at x5 |
| 7 | Replay | a stored match played at 0.25x to 8x with play/pause, trails, Voronoi, detected-only toggle, and the stats panel on click | frames sent = tracked seconds of the match; the panel at the last second equals the Gold totals; payload size measured; you play goal 5 of m001 at 4x |
| 8 | Dagster + Behind the data | a Dagster asset graph (ingestion to Bronze, Silver, Gold, Soda checks) where a failing check blocks what follows; the Data quality, Pipeline & lineage and Sources & limits pages | one green Dagster run for a match; one run with a damaged table that stops at the check; the three pages in a browser |
| 9 | Design and logo | MatchLens logo, colours and type, light and dark, cards and pitch in the same style | screenshots of every page in light and dark; no horizontal scroll at phone width (390 px) |
| 10 | Demo preparation | the producer option "start at `mm:ss`" (so a replay can start 30 s before a goal), a command that empties the Kafka topics before a demo, and the demo script of section 13 | two timed dry runs of section 13 with a stopwatch, each under 10 minutes; a fresh start shows only the demo replay |

## 13. Demo script (10 minutes)

Before the jury arrives: stack up, Kafka topics emptied (step 10), Gold built for every match, the app open on Home.

| Time | Where | What happens | What we say |
|---|---|---|---|
| 0:00 - 0:30 | Home | the logo, "I am a Fan / I am a Coach", the Match library | one website, two personas, the same data |
| 0:30 - 2:30 | LIVE / Live match | start `make replay` of m001 at x1 from 04:56; at 05:26 K. Jelacic scores, the score turns 1-0 within a second; click a Brisbane player: distance, top speed, sprints and heatmap so far; the 5-minute panel fills from Spark Streaming | Kafka at the speed of the real match; the live pitch and the streaming job read the same topics |
| 2:30 - 4:00 | FAN VIEW | Match story of m001 (goals, momentum, possession, 3 key differences); Squad; open a player's page (scores, heatmap, top speed); his column in another match (F8) | every number answers a fan's question and says its limits |
| 4:00 - 5:45 | COACH VIEW | Team analysis (shape with and without the ball, pressing by third, build-up, attack side); Physical & fatigue (who faded); Event explorer filtered on one player's runs | the same tables, read by a coach |
| 5:45 - 6:45 | MATCHES / Compare matches | Brisbane Roar in three matches side by side, opponents named | "is this how the team usually plays?" |
| 6:45 - 8:00 | MATCHES / Replay | m001 from 64:30, the 2-3 goal of A. Goodwin at 64:50, at 2x then 0.5x, Voronoi on, detected-only on; click the scorer: the stats panel | the replay of a stored match, our own viewer |
| 8:00 - 9:30 | BEHIND THE DATA | Pipeline & lineage (Dagster graph, dbt lineage); Data quality: run the damaged-data demo and show the failing Soda check and the step it blocks | we trust a number because a check would stop it |
| 9:30 - 10:00 | Sources & limits | SkillCorner open data, 1 Hz, estimated positions, no xG | what the data cannot say |

The live clock is the replay clock (`ts`); the goal at 05:26 is `ts` 326 in Gold. The producer takes the start as `mm:ss`
(step 10), so the replay starts at 04:56, 30 s before the goal.

## 14. More matches

SkillCorner open data has 20 A-League 2024/25 matches today (not 14): 10 on a 105 x 68 pitch, ours included, 4 on
104 x 68 and 6 on 106 x 68 (read from each `match.json` on 2026-11-15). Silver puts every match on 105 x 68 and the
Soda checks enforce it, so only the 8 other 105 x 68 matches can be added without changing Silver:

| SkillCorner id | Date | Match | Score |
|---|---|---|---|
| 1927964 | 2024-12-22 | Western Sydney - Wellington Phoenix | 4-1 |
| 1953632 | 2024-12-31 | Central Coast Mariners - Melbourne City | 1-1 |
| 1986691 | 2025-01-26 | Western Sydney - Auckland FC | 0-1 |
| 1996435 | 2025-02-01 | Sydney FC - Adelaide United | 4-1 |
| 2006229 | 2025-03-07 | Melbourne City - Macarthur FC | 2-0 |
| 2007448 | 2025-03-15 | Perth Glory - Brisbane Roar | 1-3 |
| 2011166 | 2025-04-12 | Wellington Phoenix - Melbourne Victory | 2-3 |
| 2017461 | 2025-05-17 | Melbourne Victory - Auckland FC | 0-1 |

Decided (review of 2026-11-15): 2007448 and 1996435 are added in step 5; 2011166 only if time allows; 1927964 is not added.

1. **2007448, Perth Glory 1-3 Brisbane Roar.** The demo team's third match, its only away match, and a rematch of m002
   (Brisbane 0-1 Perth). It gives F8 three columns and C7 a home/away comparison against the same opponent.
2. **1996435, Sydney FC 4-1 Adelaide United.** Adelaide, the winner of m001, in a second match: Compare can then show
   the opponent too, and 5 goals give the fan pages something to tell.
3. **2011166, Wellington Phoenix 2-3 Melbourne Victory.** 5 goals and a one-goal finish: a second match to demo the
   live page and the replay, with two new teams.
4. Optional: **1927964, Western Sydney 4-1 Wellington Phoenix.** It already went through ingestion and Gold once (the
   "m002" of the first zip, `dbt/README.md`), so it is the lowest-risk fourth match; it also brings Wellington twice
   with 3.

Not proposed: the 104 x 68 and 106 x 68 matches. They would need Silver to keep each match's own pitch size, and every
x_att, third, lane and space-control grid to follow it.
