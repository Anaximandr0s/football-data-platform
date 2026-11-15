-- Grain: one row per player per match (C6). dpm in the first 15 minutes on the pitch (start_ts <= ts < start_ts + 900)
-- and in the last 5 (end_ts - 300 < ts <= end_ts). is_eligible: outfield, at least 30 minutes on the pitch, at least
-- 5 tracked minutes in the first window and 2 in the last; the others keep their values and are greyed out.
with w as (
    select t.match_id, t.player_id,
           sum(t.speed_kmh / 3.6) filter (where t.ts >= p.start_ts and t.ts < p.start_ts + 900)  as distance_first15,
           count(t.speed_kmh)     filter (where t.ts >= p.start_ts and t.ts < p.start_ts + 900)  as speed_seconds_first15,
           count(*)               filter (where t.ts >= p.start_ts and t.ts < p.start_ts + 900)  as rows_first15,
           sum(t.speed_kmh / 3.6) filter (where t.ts > p.end_ts - 300 and t.ts <= p.end_ts)      as distance_last5,
           count(t.speed_kmh)     filter (where t.ts > p.end_ts - 300 and t.ts <= p.end_ts)      as speed_seconds_last5,
           count(*)               filter (where t.ts > p.end_ts - 300 and t.ts <= p.end_ts)      as rows_last5
    from {{ ref('stg_tracking') }} t
    join {{ ref('stg_players') }} p using (match_id, player_id)
    group by 1, 2
),

d as (
    select p.match_id, p.player_id, p.team_id, p.short_name, p.position, p.start_ts, p.end_ts,
           p.position != 'GK'                                              as is_outfield,
           (p.end_ts - p.start_ts) / 60.0                                  as minutes_on_pitch,
           w.distance_first15 / nullif(w.speed_seconds_first15 / 60.0, 0) as dpm_first15,
           w.distance_last5   / nullif(w.speed_seconds_last5 / 60.0, 0)   as dpm_last5,
           coalesce(w.rows_first15, 0) / 60.0                              as tracked_minutes_first15,
           coalesce(w.rows_last5, 0) / 60.0                                as tracked_minutes_last5
    from {{ ref('stg_players') }} p
    left join w using (match_id, player_id)
)

select
    match_id, player_id, team_id, short_name, position, start_ts, end_ts, is_outfield,
    round(minutes_on_pitch, 1)        as minutes_on_pitch,
    round(dpm_first15, 1)             as dpm_first15,
    round(dpm_last5, 1)               as dpm_last5,
    round(1 - dpm_last5 / nullif(dpm_first15, 0), 4) as drop,
    round(tracked_minutes_first15, 2) as tracked_minutes_first15,
    round(tracked_minutes_last5, 2)   as tracked_minutes_last5,
    is_outfield and minutes_on_pitch >= 30 and tracked_minutes_first15 >= 5 and tracked_minutes_last5 >= 2 as is_eligible
from d
