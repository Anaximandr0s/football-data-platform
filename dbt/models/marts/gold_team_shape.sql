-- Grain: one row per team per phase per match (C1, C2): means over the tracked seconds of int_team_shape_second.
-- C2 reads defensive_line_height on the out_of_possession row. detected_share = positions seen by the camera / positions used.
select
    match_id, team_id, phase,
    count(*)                                              as seconds_used,
    round(avg(width), 2)                                  as width,
    round(avg(length), 2)                                 as length,
    round(avg(area), 1)                                   as area,
    round(avg(defensive_line_height), 2)                  as defensive_line_height,
    round(sum(detected_players) / sum(outfield_players), 4) as detected_share
from {{ ref('int_team_shape_second') }}
group by match_id, team_id, phase
