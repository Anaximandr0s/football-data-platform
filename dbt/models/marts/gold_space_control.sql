-- Grain: one row per team per 5-minute football window (int_football_windows) per match with at least one tracked
-- second (S1). space_share =
-- mean over the tracked seconds of the window of the share of the 1 m cells nearest to a player of the team, all
-- positions used (detected or not); split by the ball owner of the second. detected_share sits next to it.
with s as (
    select sc.*, b.possession,
           {{ football_window('sc.ts', 'sc.period', 'm.p1_start_ts', 'm.p2_start_ts', 300) }} as window_index
    from {{ ref('int_space_control_second') }} sc
    join {{ ref('stg_matches') }} m using (match_id)
    left join {{ ref('stg_ball') }} b using (match_id, ts)
),

t as (
    select s.match_id, s.ts, s.window_index, s.players, s.detected_players, t.team_id,
           case when t.team_id = 'HOME' then s.home_share else 1 - s.home_share end as space_share,
           case when s.possession = t.team_id then 'in_possession'
                when s.possession is not null then 'out_of_possession'
                else 'unknown' end as phase
    from s cross join (values ('HOME'), ('AWAY')) t(team_id)
)

select
    t.match_id, t.team_id, t.window_index, w.period, w.window_label, w.window_start_ts, w.window_end_ts,
    w.window_seconds,
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
join {{ ref('int_football_windows') }} w
    on w.match_id = t.match_id and w.window_size = 300 and w.window_index = t.window_index
group by 1, 2, 3, 4, 5, 6, 7, 8
