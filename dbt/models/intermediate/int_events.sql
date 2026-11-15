-- Grain: one row per Silver event (runs included), with the coordinates seen by the team of the event and the two
-- flags the Gold tables count. A defensive action is pressure + tackle + foul (docs/product.md, section 2).
select
    e.*,
    {{ x_att('e.team_id', 'e.x_start') }} as x_att_start,
    {{ y_att('e.team_id', 'e.y_start') }} as y_att_start,
    {{ x_att('e.team_id', 'e.x_end') }}   as x_att_end,
    {{ y_att('e.team_id', 'e.y_end') }}   as y_att_end,
    e.type in ('pressure', 'tackle', 'foul') as is_defensive_action,
    coalesce(e.type = 'pass' and {{ x_att('e.team_id', 'e.x_end') }} - {{ x_att('e.team_id', 'e.x_start') }} >= 10,
             false) as is_progressive
from {{ ref('stg_events') }} e
