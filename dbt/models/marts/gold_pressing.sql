-- Grain: one row per team per 15-minute football window per match (int_football_windows: 0-15', 15-30', 30-45', 45+,
-- 45-60', 60-75', 75-90', 90+), every window of the match (C3). ppp = defensive actions of the team / passes of the
-- opponent in the window; thirds by x_att of the action start.
with windows as (
    select match_id, window_index, period, window_label, window_start_ts, window_end_ts, window_seconds
    from {{ ref('int_football_windows') }}
    where window_size = 900
),

teams as (
    select w.*, t.team_id, t.opponent_id
    from windows w cross join (values ('HOME', 'AWAY'), ('AWAY', 'HOME')) t(team_id, opponent_id)
),

da as (
    select e.match_id, e.team_id,
           {{ football_window('e.ts', 'e.period', 'm.p1_start_ts', 'm.p2_start_ts', 900) }} as window_index,
           count(*)                                      as defensive_actions,
           count(*) filter (where e.x_att_start < 35)    as defensive_actions_own_third,
           count(*) filter (where e.x_att_start >= 35 and e.x_att_start < 70) as defensive_actions_middle_third,
           count(*) filter (where e.x_att_start >= 70)   as defensive_actions_final_third
    from {{ ref('int_events') }} e
    join {{ ref('stg_matches') }} m using (match_id)
    where e.is_defensive_action
    group by 1, 2, 3
),

passes as (
    select e.match_id, e.team_id,
           {{ football_window('e.ts', 'e.period', 'm.p1_start_ts', 'm.p2_start_ts', 900) }} as window_index,
           count(*) as passes
    from {{ ref('stg_events') }} e
    join {{ ref('stg_matches') }} m using (match_id)
    where e.type = 'pass'
    group by 1, 2, 3
)

select
    t.match_id, t.team_id, t.window_index, t.period, t.window_label, t.window_start_ts, t.window_end_ts,
    t.window_seconds,
    coalesce(da.defensive_actions, 0)              as defensive_actions,
    coalesce(p.passes, 0)                          as opponent_passes,
    round(coalesce(da.defensive_actions, 0) / nullif(p.passes, 0), 4) as ppp,
    coalesce(da.defensive_actions_own_third, 0)    as defensive_actions_own_third,
    coalesce(da.defensive_actions_middle_third, 0) as defensive_actions_middle_third,
    coalesce(da.defensive_actions_final_third, 0)  as defensive_actions_final_third,
    round(da.defensive_actions_final_third / nullif(da.defensive_actions, 0), 4) as high_press_share
from teams t
left join da on da.match_id = t.match_id and da.team_id = t.team_id and da.window_index = t.window_index
left join passes p on p.match_id = t.match_id and p.team_id = t.opponent_id and p.window_index = t.window_index
