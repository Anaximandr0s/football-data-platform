-- Grain: one row per passer, receiver and match (passes with a known receiver). Node positions: avg_x / avg_y of
-- gold_player_match_stats.
select
    e.match_id,
    e.player_id   as passer_id,
    e.receiver_id,
    e.team_id,
    a.short_name  as passer_name,
    b.short_name  as receiver_name,
    count(*)                                              as passes,
    count(*) filter (where e.outcome = 'successful')      as passes_successful,
    round(avg(e.x_start), 2) as avg_start_x, round(avg(e.y_start), 2) as avg_start_y,
    round(avg(e.x_end), 2)   as avg_end_x,   round(avg(e.y_end), 2)   as avg_end_y
from {{ ref('stg_events') }} e
left join {{ ref('stg_players') }} a on a.match_id = e.match_id and a.player_id = e.player_id
left join {{ ref('stg_players') }} b on b.match_id = e.match_id and b.player_id = e.receiver_id
where e.type = 'pass' and e.receiver_id is not null
group by e.match_id, e.player_id, e.receiver_id, e.team_id, a.short_name, b.short_name
