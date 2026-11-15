-- Grain: one row per event, runs included (E1). The Silver columns plus names, the coordinates seen by the team of the
-- event (x_att, y_att) and the third and lane of its start.
select
    e.* exclude (is_defensive_action, is_progressive),
    p.short_name as player_short_name,
    p.shirt_number,
    r.short_name as receiver_short_name,
    {{ third('e.x_att_start') }} as third,
    {{ lane('e.y_att_start') }}  as lane
from {{ ref('int_events') }} e
left join {{ ref('stg_players') }} p on p.match_id = e.match_id and p.player_id = e.player_id
left join {{ ref('stg_players') }} r on r.match_id = e.match_id and r.player_id = e.receiver_id
