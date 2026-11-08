-- Grain: one row per player per match (FOO-04). Distances, speeds and sprints cover TRACKED seconds only
-- (about 3/4 of the match, see docs/gold-guide.md) and come from 1 Hz positions: approximate by construction.
with trk_flagged as (
    select match_id, player_id, ts, speed_kmh, is_sprint, x, y,
           lag(is_sprint) over w as prev_sprint,
           lag(ts) over w as prev_ts
    from {{ ref('stg_tracking') }}
    window w as (partition by match_id, player_id order by ts)
),

trk as (
    select match_id, player_id,
           count(*)                                   as tracked_seconds,
           sum(speed_kmh / 3.6)                       as distance_m,      -- null speeds are skipped
           count(*) filter (where is_sprint)          as sprint_seconds,
           -- a sprint second that does not continue the previous second starts a new effort
           count(*) filter (where is_sprint
                            and not (coalesce(prev_sprint, false) and ts - prev_ts = 1)) as sprint_count,
           max(speed_kmh)                             as max_speed_kmh,
           avg(speed_kmh)                             as avg_speed_kmh,
           avg(x)                                     as avg_x,
           avg(y)                                     as avg_y
    from trk_flagged
    group by match_id, player_id
),

act as (
    select match_id, player_id,
           count(*) filter (where type = 'pass')                              as passes,
           count(*) filter (where type = 'pass' and outcome = 'successful')   as passes_successful,
           count(*) filter (where type = 'shot')                              as shots,
           count(*) filter (where type = 'goal')                              as goals,
           count(*) filter (where type = 'tackle')                            as tackles,
           count(*) filter (where type = 'foul')                              as fouls,
           count(*) filter (where type = 'pressure')                          as pressures
    from {{ ref('stg_events') }}
    group by match_id, player_id
),

recv as (
    select match_id, receiver_id as player_id, count(*) as passes_received
    from {{ ref('stg_events') }}
    where type = 'pass' and receiver_id is not null
    group by match_id, receiver_id
)

select
    p.match_id, p.player_id, p.team_id, p.name, p.short_name, p.position, p.shirt_number,
    round((p.end_ts - p.start_ts) / 60.0, 1)                as minutes_on_pitch,
    coalesce(trk.tracked_seconds, 0)                        as tracked_seconds,
    round(coalesce(trk.distance_m, 0), 1)                   as distance_m,
    round(coalesce(trk.distance_m, 0) / 1000.0, 3)          as distance_km,
    coalesce(trk.sprint_seconds, 0)                         as sprint_seconds,
    coalesce(trk.sprint_count, 0)                           as sprint_count,
    round(trk.max_speed_kmh, 2)                             as max_speed_kmh,
    round(trk.avg_speed_kmh, 2)                             as avg_speed_kmh,
    round(trk.avg_x, 2)                                     as avg_x,
    round(trk.avg_y, 2)                                     as avg_y,
    coalesce(act.passes, 0)                                 as passes,
    coalesce(act.passes_successful, 0)                      as passes_successful,
    coalesce(recv.passes_received, 0)                       as passes_received,
    coalesce(act.shots, 0)                                  as shots,
    coalesce(act.goals, 0)                                  as goals,
    coalesce(act.tackles, 0)                                as tackles,
    coalesce(act.fouls, 0)                                  as fouls,
    coalesce(act.pressures, 0)                              as pressures
from {{ ref('stg_players') }} p
left join trk  using (match_id, player_id)
left join act  using (match_id, player_id)
left join recv using (match_id, player_id)
