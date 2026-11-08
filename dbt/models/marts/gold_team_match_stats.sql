-- Grain: one row per team per match. Sums of gold_player_match_stats; possession is not in the source.
with players as (
    select match_id, team_id,
           sum(distance_m)         as distance_m,
           sum(sprint_count)::bigint       as sprint_count,
           sum(sprint_seconds)::bigint     as sprint_seconds,
           max(max_speed_kmh)      as max_speed_kmh,
           sum(passes)::bigint             as passes,
           sum(passes_successful)::bigint  as passes_successful,
           sum(shots)::bigint              as shots,
           sum(goals)::bigint              as goals,
           sum(tackles)::bigint            as tackles,
           sum(fouls)::bigint              as fouls,
           sum(pressures)::bigint          as pressures
    from {{ ref('gold_player_match_stats') }}
    group by match_id, team_id
),

pos as (
    select match_id, team_id, avg(x) as avg_x, avg(y) as avg_y
    from {{ ref('stg_tracking') }}
    group by match_id, team_id
)

select
    pl.match_id, pl.team_id,
    case when pl.team_id = 'HOME' then m.home_team       else m.away_team       end as team_name,
    case when pl.team_id = 'HOME' then m.home_team_short else m.away_team_short end as team_short,
    case when pl.team_id = 'HOME' then m.home_color      else m.away_color      end as team_color,
    case when pl.team_id = 'HOME' then m.home_score      else m.away_score      end as score,
    case when pl.team_id = 'HOME' then m.away_score      else m.home_score      end as opponent_score,
    round(pl.distance_m / 1000.0, 3)                                             as distance_km,
    pl.sprint_count, pl.sprint_seconds, pl.max_speed_kmh,
    pl.passes, pl.passes_successful,
    round(pl.passes_successful * 1.0 / nullif(pl.passes, 0), 3)                  as pass_accuracy,
    pl.shots, pl.goals, pl.tackles, pl.fouls, pl.pressures,
    round(pos.avg_x, 2) as avg_x, round(pos.avg_y, 2) as avg_y
from players pl
join {{ ref('stg_matches') }} m using (match_id)
left join pos using (match_id, team_id)
