-- Grain: one row per team per 5-minute window (ts // 300) per match with at least one tracked second (S1). space_share =
-- mean over the tracked seconds of the window of the share of the 1 m cells nearest to a player of the team, all
-- positions used (detected or not); split by the ball owner of the second. detected_share sits next to it.
with s as (
    select sc.*, b.possession
    from {{ ref('int_space_control_second') }} sc
    left join {{ ref('stg_ball') }} b using (match_id, ts)
),

t as (
    select s.match_id, s.ts, s.players, s.detected_players, t.team_id,
           case when t.team_id = 'HOME' then s.home_share else 1 - s.home_share end as space_share,
           case when s.possession = t.team_id then 'in_possession'
                when s.possession is not null then 'out_of_possession'
                else 'unknown' end as phase
    from s cross join (values ('HOME'), ('AWAY')) t(team_id)
)

select
    match_id, team_id, ts // 300 as window_index,
    (ts // 300) * 300       as window_start_ts,
    (ts // 300) * 300 + 300 as window_end_ts,
    count(*)                                                          as seconds_used,
    round(avg(space_share), 4)                                        as space_share,
    count(*) filter (where phase = 'in_possession')                   as seconds_in_possession,
    round(avg(space_share) filter (where phase = 'in_possession'), 4) as space_share_in_possession,
    count(*) filter (where phase = 'out_of_possession')               as seconds_out_of_possession,
    round(avg(space_share) filter (where phase = 'out_of_possession'), 4) as space_share_out_of_possession,
    count(*) filter (where phase = 'unknown')                         as seconds_unknown,
    round(avg(space_share) filter (where phase = 'unknown'), 4)       as space_share_unknown,
    round(sum(detected_players) / sum(players), 4)                    as detected_share
from t
group by 1, 2, 3
