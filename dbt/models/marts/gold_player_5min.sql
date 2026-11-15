-- Grain: one row per player per 5-minute football window per match (int_football_windows: 0-5' ... 40-45', 45+,
-- 45-50' ... 85-90', 90+). `coverage` = tracked seconds / length of the window (a stoppage window can be short or
-- long): a low value means the numbers of that window are incomplete. Batch twin of the streaming job (FOO-08).
with trk as (
    select t.match_id, t.player_id,
           {{ football_window('t.ts', 't.period', 'm.p1_start_ts', 'm.p2_start_ts', 300) }} as window_index,
           count(*)                             as tracked_seconds,
           sum(t.speed_kmh / 3.6)               as distance_m,
           count(*) filter (where t.is_sprint)  as sprint_seconds,
           max(t.speed_kmh)                     as max_speed_kmh
    from {{ ref('stg_tracking') }} t
    join {{ ref('stg_matches') }} m using (match_id)
    group by 1, 2, 3
),

act as (
    select e.match_id, e.player_id,
           {{ football_window('e.ts', 'e.period', 'm.p1_start_ts', 'm.p2_start_ts', 300) }} as window_index,
           count(*) filter (where e.type = 'pass')     as passes,
           count(*) filter (where e.type = 'shot')     as shots,
           count(*) filter (where e.type = 'goal')     as goals,
           count(*) filter (where e.type = 'tackle')   as tackles,
           count(*) filter (where e.type = 'foul')     as fouls,
           count(*) filter (where e.type = 'pressure') as pressures
    from {{ ref('stg_events') }} e
    join {{ ref('stg_matches') }} m using (match_id)
    where e.type != 'run'   -- a run is not an action: it must not open a window row of its own
    group by 1, 2, 3
)

select
    match_id, player_id, p.team_id, window_index, w.period, w.window_label, w.window_start_ts, w.window_end_ts,
    w.window_seconds,
    coalesce(trk.tracked_seconds, 0)                                                as tracked_seconds,
    round(coalesce(trk.tracked_seconds, 0) * 1.0 / w.window_seconds, 3)             as coverage,
    round(coalesce(trk.distance_m, 0), 1)                                           as distance_m,
    coalesce(trk.sprint_seconds, 0)                                                 as sprint_seconds,
    round(trk.max_speed_kmh, 2)                                                     as max_speed_kmh,
    coalesce(act.passes, 0) as passes, coalesce(act.shots, 0) as shots, coalesce(act.goals, 0) as goals,
    coalesce(act.tackles, 0) as tackles, coalesce(act.fouls, 0) as fouls, coalesce(act.pressures, 0) as pressures
from trk
full outer join act using (match_id, player_id, window_index)
left join {{ ref('stg_players') }} p using (match_id, player_id)
join {{ ref('int_football_windows') }} w using (match_id, window_index)
where w.window_size = 300
