-- Grain: one row per team per 5-minute football window per match (int_football_windows: 0-5' ... 40-45', 45+,
-- 45-50' ... 85-90', 90+), every window of the match, even an empty one (F1, F2, F7, E2). A window with fewer than
-- 60 seconds of known possession is flagged, not removed; a short stoppage window keeps its own length.
with windows as (
    select match_id, window_index, period, window_label, window_start_ts, window_end_ts, window_seconds
    from {{ ref('int_football_windows') }}
    where window_size = 300
),

teams as (
    select w.*, t.team_id
    from windows w cross join (values ('HOME'), ('AWAY')) t(team_id)
),

ev as (
    select e.match_id, e.team_id,
           {{ football_window('e.ts', 'e.period', 'm.p1_start_ts', 'm.p2_start_ts', 300) }} as window_index,
           count(*) filter (where e.type = 'pass')                          as passes,
           count(*) filter (where e.type = 'pass' and e.x_att_start >= 70)  as final_third_passes,
           count(*) filter (where e.type = 'shot')                          as shots,
           count(*) filter (where e.type = 'goal')                          as goals,
           count(*) filter (where e.is_defensive_action)                    as defensive_actions,
           sum(e.xthreat) filter (where e.type = 'pass' and e.outcome = 'successful') as xthreat_successful_passes
    from {{ ref('int_events') }} e
    join {{ ref('stg_matches') }} m using (match_id)
    where e.type != 'run'
    group by 1, 2, 3
),

poss as (
    select b.match_id,
           {{ football_window('b.ts', 'b.period', 'm.p1_start_ts', 'm.p2_start_ts', 300) }} as window_index,
           count(*) filter (where b.possession = 'HOME') as home_seconds,
           count(*) filter (where b.possession = 'AWAY') as away_seconds
    from {{ ref('stg_ball') }} b
    join {{ ref('stg_matches') }} m using (match_id)
    group by 1, 2
),

counts as (
    select t.match_id, t.team_id, t.window_index, t.period, t.window_label, t.window_start_ts, t.window_end_ts,
           t.window_seconds,
           coalesce(ev.passes, 0)              as passes,
           coalesce(ev.final_third_passes, 0)  as final_third_passes,
           coalesce(ev.shots, 0)               as shots,
           coalesce(ev.goals, 0)               as goals,
           coalesce(ev.defensive_actions, 0)   as defensive_actions,
           round(coalesce(ev.xthreat_successful_passes, 0), 4) as xthreat_successful_passes,
           coalesce(case when t.team_id = 'HOME' then poss.home_seconds else poss.away_seconds end, 0) as possession_seconds,
           coalesce(poss.home_seconds + poss.away_seconds, 0)  as known_seconds
    from teams t
    left join ev   using (match_id, team_id, window_index)
    left join poss using (match_id, window_index)
)

select
    match_id, team_id, window_index, period, window_label, window_start_ts, window_end_ts, window_seconds,
    passes, final_third_passes,
    round(final_third_passes / nullif(sum(final_third_passes) over (partition by match_id, window_index), 0), 4) as field_tilt,
    possession_seconds, known_seconds,
    round(possession_seconds / nullif(known_seconds, 0), 4) as possession_share,
    known_seconds < 60                                      as possession_greyed,
    shots, goals, defensive_actions, xthreat_successful_passes,
    sum(goals) filter (where team_id = 'HOME') over (partition by match_id order by window_index)::int as score_home_end,
    sum(goals) filter (where team_id = 'AWAY') over (partition by match_id order by window_index)::int as score_away_end
from counts
