-- Grain: one row per match per tracked second per object: each player on the pitch, and the ball (object_id 'ball').
-- What the Replay page plays (R1, S1): positions in the Silver frame (HOME attacks toward x = 105 in both halves), with
-- the owner of the ball and the HOME space share of the second. Seconds without tracking (camera gaps) have no row.
with objects as (
    select match_id, ts, period, player_id as object_id, 'player' as object_type, team_id, x, y, null::double as z,
           speed_kmh, is_detected
    from {{ ref('stg_tracking') }}
    union all
    select match_id, ts, period, 'ball', 'ball', null, x, y, z, null, null
    from {{ ref('stg_ball') }}
)

select
    o.match_id, o.ts, o.period, o.object_id, o.object_type, o.team_id, p.shirt_number, p.position, o.x, o.y, o.z,
    o.speed_kmh, o.is_detected, b.possession, s.home_share as home_space_share
from objects o
left join {{ ref('stg_players') }} p on p.match_id = o.match_id and p.player_id = o.object_id
left join {{ ref('stg_ball') }} b on b.match_id = o.match_id and b.ts = o.ts
left join {{ ref('int_space_control_second') }} s on s.match_id = o.match_id and s.ts = o.ts
