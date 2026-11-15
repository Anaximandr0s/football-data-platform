-- Failing rows = goals in gold_shots (total and running score) that differ from the final score of silver.matches.
with shots as (
    select match_id,
           count(*) filter (where is_goal and team_id = 'HOME') as goals_home,
           count(*) filter (where is_goal and team_id = 'AWAY') as goals_away,
           max(score_home_after) as last_home, max(score_away_after) as last_away
    from {{ ref('gold_shots') }}
    group by match_id
)
select m.match_id, m.home_score, m.away_score, s.goals_home, s.goals_away, s.last_home, s.last_away
from {{ ref('stg_matches') }} m
left join shots s using (match_id)
where coalesce(s.goals_home, 0) != m.home_score or coalesce(s.goals_away, 0) != m.away_score
   or coalesce(s.last_home, 0)  != m.home_score or coalesce(s.last_away, 0)  != m.away_score
