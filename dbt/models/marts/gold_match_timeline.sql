-- Grain: one row per team per 5-minute window (ts // 300) per match, every window from kick-off to p2_end_ts, even
-- an empty one (F1, F2, F7, E2). A window with fewer than 60 seconds of known possession is flagged, not removed.
with windows as (
    select match_id, unnest(generate_series(0, p2_end_ts // 300))::int as w
    from {{ ref('stg_matches') }}
),

teams as (
    select w.match_id, w.w, t.team_id
    from windows w cross join (values ('HOME'), ('AWAY')) t(team_id)
),

ev as (
    select match_id, team_id, ts // 300 as w,
           count(*) filter (where type = 'pass')                          as passes,
           count(*) filter (where type = 'pass' and x_att_start >= 70)    as final_third_passes,
           count(*) filter (where type = 'shot')                          as shots,
           count(*) filter (where type = 'goal')                          as goals,
           count(*) filter (where is_defensive_action)                    as defensive_actions,
           sum(xthreat) filter (where type = 'pass' and outcome = 'successful') as xthreat_successful_passes
    from {{ ref('int_events') }}
    where type != 'run'
    group by 1, 2, 3
),

poss as (
    select match_id, ts // 300 as w,
           count(*) filter (where possession = 'HOME') as home_seconds,
           count(*) filter (where possession = 'AWAY') as away_seconds
    from {{ ref('stg_ball') }}
    group by 1, 2
),

counts as (
    select t.match_id, t.team_id, t.w,
           coalesce(ev.passes, 0)              as passes,
           coalesce(ev.final_third_passes, 0)  as final_third_passes,
           coalesce(ev.shots, 0)               as shots,
           coalesce(ev.goals, 0)               as goals,
           coalesce(ev.defensive_actions, 0)   as defensive_actions,
           round(coalesce(ev.xthreat_successful_passes, 0), 4) as xthreat_successful_passes,
           coalesce(case when t.team_id = 'HOME' then poss.home_seconds else poss.away_seconds end, 0) as possession_seconds,
           coalesce(poss.home_seconds + poss.away_seconds, 0)  as known_seconds
    from teams t
    left join ev   using (match_id, team_id, w)
    left join poss using (match_id, w)
)

select
    match_id, team_id, w as window_index,
    w * 300       as window_start_ts,
    w * 300 + 300 as window_end_ts,
    passes, final_third_passes,
    round(final_third_passes / nullif(sum(final_third_passes) over (partition by match_id, w), 0), 4) as field_tilt,
    possession_seconds, known_seconds,
    round(possession_seconds / nullif(known_seconds, 0), 4) as possession_share,
    known_seconds < 60                                      as possession_greyed,
    shots, goals, defensive_actions, xthreat_successful_passes,
    sum(goals) filter (where team_id = 'HOME') over (partition by match_id order by w)::int as score_home_end,
    sum(goals) filter (where team_id = 'AWAY') over (partition by match_id order by w)::int as score_away_end
from counts
