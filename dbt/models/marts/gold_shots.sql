-- Grain: one row per shot or goal. The source has no saved / blocked / off-target outcome.
-- Silver frame: HOME attacks toward x = 105, AWAY toward x = 0 (events are mirrored per team in Silver),
-- so the goal a team attacks is at x = 105 for HOME and x = 0 for AWAY, centre y = pitch_width / 2.
select
    e.match_id, e.event_id, e.ts, e.period, e.player_id,
    p.name as player_name, p.short_name as player_short_name, p.shirt_number,
    e.team_id, e.type, (e.type = 'goal') as is_goal,
    e.x_start, e.y_start, e.x_end, e.y_end,
    case when e.team_id = 'HOME' then {{ var('pitch_length') }} else 0 end as attacking_goal_x,
    round(sqrt(power(e.x_start - case when e.team_id = 'HOME' then {{ var('pitch_length') }} else 0 end, 2)
             + power(e.y_start - {{ var('pitch_width') }} / 2, 2)), 2)     as distance_to_goal_m,
    sum(case when e.type = 'goal' and e.team_id = 'HOME' then 1 else 0 end)
        over (partition by e.match_id order by e.ts, e.event_id)::int       as score_home_after,
    sum(case when e.type = 'goal' and e.team_id = 'AWAY' then 1 else 0 end)
        over (partition by e.match_id order by e.ts, e.event_id)::int       as score_away_after
from {{ ref('stg_events') }} e
left join {{ ref('stg_players') }} p on p.match_id = e.match_id and p.player_id = e.player_id
where e.type in ('shot', 'goal')
