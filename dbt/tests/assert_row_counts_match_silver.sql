-- Failing rows = a Gold table that does not have the rows Silver says it should have, per match.
with expected as (
    select match_id, 'gold_player_match_stats' as model, count(*) as n from {{ ref('stg_players') }} group by 1
    union all
    select match_id, 'gold_team_match_stats', 2 from {{ ref('stg_matches') }}
    union all
    select match_id, 'gold_shots', count(*) from {{ ref('stg_events') }} where type in ('shot', 'goal') group by 1
),
got as (
    select match_id, 'gold_player_match_stats' as model, count(*) as n from {{ ref('gold_player_match_stats') }} group by 1
    union all
    select match_id, 'gold_team_match_stats', count(*) from {{ ref('gold_team_match_stats') }} group by 1
    union all
    select match_id, 'gold_shots', count(*) from {{ ref('gold_shots') }} group by 1
)
select coalesce(e.match_id, g.match_id) as match_id, coalesce(e.model, g.model) as model, e.n as expected, g.n as got
from expected e full outer join got g on e.match_id = g.match_id and e.model = g.model
where e.n is distinct from g.n
