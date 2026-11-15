-- Grain: one row per team per match (C7, F7): the team metrics of the other Gold tables over the whole match, and the
-- F7 gaps: gap = (m_team - m_opponent) / ((m_team + m_opponent) / 2), null when both are 0. Gaps state differences, not causes.
with poss as (
    select match_id,
           count(*) filter (where possession = 'HOME') as home_seconds,
           count(*) filter (where possession = 'AWAY') as away_seconds
    from {{ ref('stg_ball') }}
    group by 1
),

ev as (
    select match_id, team_id,
           count(*) filter (where type = 'pass')                       as passes,
           count(*) filter (where type = 'pass' and x_att_start >= 70) as final_third_passes,
           count(*) filter (where type in ('shot', 'goal'))            as shots_and_goals,
           count(*) filter (where is_defensive_action)                 as defensive_actions,
           count(*) filter (where is_defensive_action and x_att_start >= 70) as defensive_actions_final_third
    from {{ ref('int_events') }}
    group by 1, 2
),

shape as (
    select match_id, team_id, avg(width) as width, avg(length) as length,
           avg(defensive_line_height) filter (where phase = 'out_of_possession') as defensive_line_height
    from {{ ref('int_team_shape_second') }}
    group by 1, 2
),

run as (
    select t.match_id, t.team_id, sum(t.speed_kmh / 3.6) / nullif(count(t.speed_kmh) / 60.0, 0) as dpm_outfield
    from {{ ref('stg_tracking') }} t
    join {{ ref('stg_players') }} p using (match_id, player_id)
    where p.position != 'GK'
    group by 1, 2
),

m as (
    select
        b.match_id, b.team_id,
        case when b.team_id = 'HOME' then mt.home_team else mt.away_team end as team_name,
        case when b.team_id = 'HOME' then mt.away_team else mt.home_team end as opponent_name,
        case when b.team_id = 'HOME' then poss.home_seconds else poss.away_seconds end
            / nullif(poss.home_seconds + poss.away_seconds, 0)                      as possession_share,
        ev.final_third_passes / nullif(ev.final_third_passes + o.final_third_passes, 0) as field_tilt,
        ev.shots_and_goals,
        shape.width, shape.length, shape.defensive_line_height,
        ev.defensive_actions / nullif(o.passes, 0)                                  as ppp,
        ev.defensive_actions_final_third / nullif(ev.defensive_actions, 0)          as high_press_share,
        b.progressive_passes, b.progressive_passes_per90,
        run.dpm_outfield,
        b.share_left, b.share_centre, b.share_right
    from {{ ref('gold_team_build_up') }} b
    join {{ ref('stg_matches') }} mt using (match_id)
    join poss using (match_id)
    left join ev on ev.match_id = b.match_id and ev.team_id = b.team_id
    left join ev o on o.match_id = b.match_id and o.team_id != b.team_id
    left join shape on shape.match_id = b.match_id and shape.team_id = b.team_id
    left join run on run.match_id = b.match_id and run.team_id = b.team_id
)

select
    t.match_id, t.team_id, t.team_name, t.opponent_name,
    round(t.possession_share, 4) as possession_share, round(t.field_tilt, 4) as field_tilt, t.shots_and_goals,
    round(t.width, 2) as width, round(t.length, 2) as length, round(t.defensive_line_height, 2) as defensive_line_height,
    round(t.ppp, 4) as ppp, round(t.high_press_share, 4) as high_press_share,
    t.progressive_passes, t.progressive_passes_per90, round(t.dpm_outfield, 1) as dpm_outfield,
    t.share_left, t.share_centre, t.share_right,
    {%- for metric in ['possession_share', 'field_tilt', 'shots_and_goals', 'progressive_passes', 'ppp', 'dpm_outfield'] %}
    round((t.{{ metric }} - o.{{ metric }}) / nullif((t.{{ metric }} + o.{{ metric }}) / 2, 0), 4) as gap_{{ metric }}{{ ',' if not loop.last }}
    {%- endfor %}
from m t
join m o on o.match_id = t.match_id and o.team_id != t.team_id
