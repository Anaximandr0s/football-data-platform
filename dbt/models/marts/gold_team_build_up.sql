-- Grain: one row per team per match (C4, C5). Progressive pass: x_att(end) - x_att(start) >= 10. Final-third entries:
-- successful passes ending at x_att >= 70 (those starting there too), split by lane of y_att at the end.
-- tracked_minutes = count(*) / 60 of the team's tracking rows, so per_tracked_minute is per player-minute.
with ev as (
    select match_id, team_id,
           count(*) filter (where is_progressive)                                      as progressive_passes,
           count(*) filter (where is_progressive and outcome = 'successful')           as progressive_passes_successful,
           count(*) filter (where type = 'pass' and outcome = 'successful' and x_att_end >= 70) as final_third_entries,
           count(*) filter (where type = 'pass' and outcome = 'successful' and x_att_end >= 70 and y_att_end > 45.33) as entries_left,
           count(*) filter (where type = 'pass' and outcome = 'successful' and x_att_end >= 70 and y_att_end < 22.67) as entries_right
    from {{ ref('int_events') }}
    group by 1, 2
),

trk as (
    select match_id, team_id, count(*) / 60.0 as tracked_minutes
    from {{ ref('stg_tracking') }}
    group by 1, 2
)

select
    t.match_id, t.team_id,
    coalesce(ev.progressive_passes, 0)                   as progressive_passes,
    coalesce(ev.progressive_passes_successful, 0)        as progressive_passes_successful,
    round(ev.progressive_passes_successful / nullif(ev.progressive_passes, 0), 4) as progressive_success_rate,
    round(t.tracked_minutes, 1)                          as tracked_minutes,
    round(coalesce(ev.progressive_passes, 0) / nullif(t.tracked_minutes, 0), 5) as progressive_passes_per_tracked_minute,
    coalesce(ev.final_third_entries, 0)                  as final_third_entries,
    coalesce(ev.entries_left, 0)                         as entries_left,
    coalesce(ev.final_third_entries - ev.entries_left - ev.entries_right, 0) as entries_centre,
    coalesce(ev.entries_right, 0)                        as entries_right,
    round(ev.entries_left / nullif(ev.final_third_entries, 0), 4)            as share_left,
    round((ev.final_third_entries - ev.entries_left - ev.entries_right) / nullif(ev.final_third_entries, 0), 4) as share_centre,
    round(ev.entries_right / nullif(ev.final_third_entries, 0), 4)           as share_right
from trk t
left join ev using (match_id, team_id)
