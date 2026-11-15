-- Grain: one row per player per 5-minute window of the match clock (ts), per match. `coverage` = tracked seconds / window
-- length: a low value means the numbers of that window are incomplete. Batch twin of the streaming job (FOO-08).
with trk as (
    select match_id, player_id,
           (ts // {{ var('window_seconds') }}) * {{ var('window_seconds') }} as window_start_ts,
           count(*)                           as tracked_seconds,
           sum(speed_kmh / 3.6)               as distance_m,
           count(*) filter (where is_sprint)  as sprint_seconds,
           max(speed_kmh)                     as max_speed_kmh
    from {{ ref('stg_tracking') }}
    group by 1, 2, 3
),

act as (
    select match_id, player_id,
           (ts // {{ var('window_seconds') }}) * {{ var('window_seconds') }} as window_start_ts,
           count(*) filter (where type = 'pass')     as passes,
           count(*) filter (where type = 'shot')     as shots,
           count(*) filter (where type = 'goal')     as goals,
           count(*) filter (where type = 'tackle')   as tackles,
           count(*) filter (where type = 'foul')     as fouls,
           count(*) filter (where type = 'pressure') as pressures
    from {{ ref('stg_events') }}
    group by 1, 2, 3
)

select
    match_id, player_id, p.team_id, window_start_ts,
    window_start_ts + {{ var('window_seconds') }}                                   as window_end_ts,
    coalesce(trk.tracked_seconds, 0)                                                as tracked_seconds,
    round(coalesce(trk.tracked_seconds, 0) * 1.0 / {{ var('window_seconds') }}, 3)  as coverage,
    round(coalesce(trk.distance_m, 0), 1)                                           as distance_m,
    coalesce(trk.sprint_seconds, 0)                                                 as sprint_seconds,
    round(trk.max_speed_kmh, 2)                                                     as max_speed_kmh,
    coalesce(act.passes, 0) as passes, coalesce(act.shots, 0) as shots, coalesce(act.goals, 0) as goals,
    coalesce(act.tackles, 0) as tackles, coalesce(act.fouls, 0) as fouls, coalesce(act.pressures, 0) as pressures
from trk
full outer join act using (match_id, player_id, window_start_ts)
left join {{ ref('stg_players') }} p using (match_id, player_id)
