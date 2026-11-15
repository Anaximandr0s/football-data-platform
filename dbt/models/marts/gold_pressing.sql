-- Grain: one row per team per 15-minute window (ts // 900) per match, every window up to p2_end_ts (C3).
-- ppp = defensive actions of the team / passes of the opponent in the window; thirds by x_att of the action start.
with windows as (
    select match_id, unnest(generate_series(0, p2_end_ts // 900))::int as w
    from {{ ref('stg_matches') }}
),

teams as (
    select w.match_id, w.w, t.team_id, t.opponent_id
    from windows w cross join (values ('HOME', 'AWAY'), ('AWAY', 'HOME')) t(team_id, opponent_id)
),

da as (
    select match_id, team_id, ts // 900 as w,
           count(*)                                    as defensive_actions,
           count(*) filter (where x_att_start < 35)    as defensive_actions_own_third,
           count(*) filter (where x_att_start >= 35 and x_att_start < 70) as defensive_actions_middle_third,
           count(*) filter (where x_att_start >= 70)   as defensive_actions_final_third
    from {{ ref('int_events') }}
    where is_defensive_action
    group by 1, 2, 3
),

passes as (
    select match_id, team_id, ts // 900 as w, count(*) as passes
    from {{ ref('stg_events') }}
    where type = 'pass'
    group by 1, 2, 3
)

select
    t.match_id, t.team_id, t.w as window_index,
    t.w * 900       as window_start_ts,
    t.w * 900 + 900 as window_end_ts,
    coalesce(da.defensive_actions, 0)              as defensive_actions,
    coalesce(p.passes, 0)                          as opponent_passes,
    round(coalesce(da.defensive_actions, 0) / nullif(p.passes, 0), 4) as ppp,
    coalesce(da.defensive_actions_own_third, 0)    as defensive_actions_own_third,
    coalesce(da.defensive_actions_middle_third, 0) as defensive_actions_middle_third,
    coalesce(da.defensive_actions_final_third, 0)  as defensive_actions_final_third,
    round(da.defensive_actions_final_third / nullif(da.defensive_actions, 0), 4) as high_press_share
from teams t
left join da on da.match_id = t.match_id and da.team_id = t.team_id and da.w = t.w
left join passes p on p.match_id = t.match_id and p.team_id = t.opponent_id and p.w = t.w
