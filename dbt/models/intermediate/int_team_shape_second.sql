-- Grain: one row per team per tracked second per match (C1, C2), outfield players only (position != 'GK').
-- The defensive line is the mean x_att of the 4 deepest outfield players: it assumes a back four.
-- phase comes from the ball owner of that second: no ball row or no owner = unknown.
with pos as (
    select t.match_id, t.team_id, t.ts, t.period, t.y, t.is_detected,
           {{ x_att('t.team_id', 't.x') }} as x_att,
           row_number() over (partition by t.match_id, t.team_id, t.ts order by {{ x_att('t.team_id', 't.x') }}) as depth
    from {{ ref('stg_tracking') }} t
    join {{ ref('stg_players') }} p using (match_id, player_id)
    where p.position != 'GK'
)

select
    pos.match_id, pos.team_id, pos.ts, max(pos.period) as period,
    case when b.possession = pos.team_id then 'in_possession'
         when b.possession is not null    then 'out_of_possession'
         else 'unknown' end                                     as phase,
    count(*)                                                    as outfield_players,
    count(*) filter (where pos.is_detected)                     as detected_players,
    max(pos.y) - min(pos.y)                                     as width,
    max(pos.x_att) - min(pos.x_att)                             as length,
    (max(pos.y) - min(pos.y)) * (max(pos.x_att) - min(pos.x_att)) as area,
    avg(pos.x_att) filter (where pos.depth <= 4)                as defensive_line_height
from pos
left join {{ ref('stg_ball') }} b on b.match_id = pos.match_id and b.ts = pos.ts
group by pos.match_id, pos.team_id, pos.ts, b.possession
