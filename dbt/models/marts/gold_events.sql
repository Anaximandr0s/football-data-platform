-- Grain: one row per event, runs included (E1). The Silver columns plus names, the coordinates seen by the team of the
-- event (x_att, y_att), the third and lane of its start, and for a goal the second the ball was in the goal.
--
-- goal_ts: an event's ts is the start of the possession that ended with the shot, so the ball is not in the goal yet.
-- Within 10 s after it: the first second with the ball past the goal line the team attacks and between the posts
-- (ball_in_goal); the ball is extrapolated after many shots and the camera often cuts away, so otherwise the second
-- when the ball is nearest the goal mouth (ball_nearest_goal); with no ball at all, the event's ts. The same rule as
-- app/streamlit/goalmoment.py (Live).
with goals as (
    select match_id, event_id, ts, team_id,
           case when team_id = 'HOME' then {{ var('pitch_length') }} else 0 end as goal_x
    from {{ ref('int_events') }}
    where type = 'goal'
),

in_goal as (
    select g.event_id, min(b.ts) as goal_ts
    from goals g
    join {{ ref('stg_ball') }} b on b.match_id = g.match_id and b.ts between g.ts and g.ts + 10
    where (case when g.team_id = 'HOME' then b.x > g.goal_x else b.x < g.goal_x end)
      and abs(b.y - {{ var('pitch_width') }} / 2) <= 3.66
    group by 1
),

nearest as (
    select g.event_id, arg_min(b.ts, sqrt(power(b.x - g.goal_x, 2) + power(b.y - {{ var('pitch_width') }} / 2, 2))
                               + b.ts * 1e-6) as goal_ts           -- a tie goes to the earlier second
    from goals g
    join {{ ref('stg_ball') }} b on b.match_id = g.match_id and b.ts between g.ts and g.ts + 10
    where b.x is not null
    group by 1
),

moments as (
    select g.event_id,
           coalesce(i.goal_ts, n.goal_ts, g.ts)::integer as goal_ts,
           case when i.goal_ts is not null then 'ball_in_goal'
                when n.goal_ts is not null then 'ball_nearest_goal' else 'event_start' end as goal_ts_method
    from goals g
    left join in_goal i using (event_id)
    left join nearest n using (event_id)
)

select
    e.* exclude (is_defensive_action, is_progressive),
    p.short_name as player_short_name,
    p.shirt_number,
    r.short_name as receiver_short_name,
    {{ third('e.x_att_start') }} as third,
    {{ lane('e.y_att_start') }}  as lane,
    m.goal_ts,
    m.goal_ts_method
from {{ ref('int_events') }} e
left join {{ ref('stg_players') }} p on p.match_id = e.match_id and p.player_id = e.player_id
left join {{ ref('stg_players') }} r on r.match_id = e.match_id and r.player_id = e.receiver_id
left join moments m on m.event_id = e.event_id
