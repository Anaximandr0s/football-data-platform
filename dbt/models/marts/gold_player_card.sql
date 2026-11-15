-- Grain: one row per player per match (F3, F4, F5, F6, F8). Rates are per tracked minute (count(*) / 60 of the player's
-- tracking rows); dpm divides by the seconds that have a speed. Scores rank the eligible players of both teams
-- (outfield, at least 20 tracked minutes) inside one match: 100 = best. Other players keep their values, without scores.
with flagged as (
    select *, lag(is_detected) over (partition by match_id, player_id order by ts) as previous_detected
    from {{ ref('stg_tracking') }}
),

-- a speed joins two positions one second apart: the top speed uses only speeds whose two positions the camera saw,
-- because every speed above 33 km/h in m001 and m002 had an estimated position at one end
spd as (
    select match_id, player_id, sum(speed_kmh / 3.6) as distance_m, count(speed_kmh) as speed_seconds,
           max(speed_kmh) filter (where is_detected and previous_detected) as top_speed_kmh
    from flagged
    group by 1, 2
),

ev as (
    select match_id, player_id,
           count(*) filter (where type = 'pass' and outcome = 'successful')                    as passes_successful,
           count(*) filter (where is_progressive)                                              as progressive_passes,
           count(*) filter (where is_progressive and outcome = 'successful')                   as progressive_passes_successful,
           count(*) filter (where is_defensive_action)                                         as defensive_actions
    from {{ ref('int_events') }}
    group by 1, 2
),

recv as (
    select match_id, receiver_id as player_id, count(*) as passes_received_successful
    from {{ ref('stg_events') }}
    where type = 'pass' and outcome = 'successful' and receiver_id is not null
    group by 1, 2
),

team_passes as (
    select match_id, team_id, count(*) as team_passes_successful
    from {{ ref('stg_events') }}
    where type = 'pass' and outcome = 'successful'
    group by 1, 2
),

base as (
    select
        s.match_id, s.player_id, s.team_id, p.source_player_id, s.name, s.short_name, s.position, s.shirt_number,
        case when s.team_id = 'HOME' then m.away_team else m.home_team end   as opponent_name,
        s.position != 'GK'                                                   as is_outfield,
        s.tracked_seconds / 60.0                                             as tracked_minutes,
        s.position != 'GK' and s.tracked_seconds / 60.0 >= 20                as is_eligible,
        spd.distance_m / nullif(spd.speed_seconds / 60.0, 0)                 as dpm,
        spd.top_speed_kmh,
        s.sprint_count,
        coalesce(ev.passes_successful, 0)                                    as passes_successful,
        coalesce(ev.progressive_passes, 0)                                   as progressive_passes,
        coalesce(ev.progressive_passes_successful, 0)                        as progressive_passes_successful,
        coalesce(ev.defensive_actions, 0)                                    as defensive_actions,
        s.goals,
        coalesce(recv.passes_received_successful, 0)                         as passes_received_successful,
        tp.team_passes_successful
    from {{ ref('gold_player_match_stats') }} s
    join {{ ref('stg_players') }} p using (match_id, player_id)
    join {{ ref('stg_matches') }} m using (match_id)
    left join spd  using (match_id, player_id)
    left join ev   using (match_id, player_id)
    left join recv using (match_id, player_id)
    left join team_passes tp on tp.match_id = s.match_id and tp.team_id = s.team_id
),

rates as (
    select *,
           sprint_count                  / nullif(tracked_minutes, 0) as sprints_per_min,
           passes_successful             / nullif(tracked_minutes, 0) as passes_successful_per_min,
           progressive_passes_successful / nullif(tracked_minutes, 0) as progressive_passes_successful_per_min,
           defensive_actions             / nullif(tracked_minutes, 0) as defensive_actions_per_min,
           (passes_successful + passes_received_successful) / nullif(2 * team_passes_successful, 0) as involvement
    from base
),

scores as (
    select match_id, player_id,
           round(100 * percent_rank() over (partition by match_id order by dpm))::int                           as score_work_rate,
           round(100 * percent_rank() over (partition by match_id order by sprints_per_min))::int               as score_sprints,
           round(100 * percent_rank() over (partition by match_id order by passes_successful_per_min))::int     as score_passing,
           round(100 * percent_rank() over (partition by match_id order by progressive_passes_successful_per_min))::int as score_progression,
           round(100 * percent_rank() over (partition by match_id order by defensive_actions_per_min))::int     as score_defending
    from rates
    where is_eligible
)

select
    r.match_id, r.player_id, r.team_id, r.source_player_id, r.name, r.short_name, r.position, r.shirt_number,
    r.opponent_name, r.is_outfield, round(r.tracked_minutes, 1) as tracked_minutes, r.is_eligible,
    round(r.dpm, 1) as dpm, round(r.top_speed_kmh, 1) as top_speed_kmh,
    r.sprint_count, round(r.sprints_per_min, 4) as sprints_per_min,
    r.passes_successful, round(r.passes_successful_per_min, 4) as passes_successful_per_min,
    r.progressive_passes, r.progressive_passes_successful,
    round(r.progressive_passes_successful_per_min, 4) as progressive_passes_successful_per_min,
    r.defensive_actions, round(r.defensive_actions_per_min, 4) as defensive_actions_per_min,
    r.goals, r.passes_received_successful,
    s.score_work_rate, s.score_sprints, s.score_passing, s.score_progression, s.score_defending,
    round(r.involvement, 4) as involvement,
    coalesce(r.involvement > 0
             and r.involvement = max(r.involvement) over (partition by r.match_id, r.team_id), false) as is_hub
from rates r
left join scores s using (match_id, player_id)
