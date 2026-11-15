-- Grain: one row per player per zone per match. Grid of zones_x x zones_y cells over the pitch, in the Silver frame
-- (HOME attacks toward x = 105). x = 105 (clipped rows) stays in the last cell. Heatmap source for the app.
with cells as (
    select match_id, player_id, team_id,
           least(floor(x / {{ var('pitch_length') }} * {{ var('zones_x') }}), {{ var('zones_x') }} - 1)::int as zone_x,
           least(floor(y / {{ var('pitch_width') }}  * {{ var('zones_y') }}), {{ var('zones_y') }} - 1)::int as zone_y
    from {{ ref('stg_tracking') }}
)

select
    match_id, player_id, team_id,
    zone_y * {{ var('zones_x') }} + zone_x                                   as zone_id,
    zone_x, zone_y,
    round(zone_x * {{ var('pitch_length') }} / {{ var('zones_x') }}, 2)       as x_min,
    round((zone_x + 1) * {{ var('pitch_length') }} / {{ var('zones_x') }}, 2) as x_max,
    round(zone_y * {{ var('pitch_width') }} / {{ var('zones_y') }}, 2)        as y_min,
    round((zone_y + 1) * {{ var('pitch_width') }} / {{ var('zones_y') }}, 2)  as y_max,
    count(*)                                                                  as seconds,
    round(count(*) * 1.0 / sum(count(*)) over (partition by match_id, player_id), 4) as share_of_tracked_seconds
from cells
group by match_id, player_id, team_id, zone_x, zone_y
