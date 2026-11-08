-- Failing rows = a pass between two players who are not in the same team (a broken receiver_id or team_id).
select n.match_id, n.passer_id, n.receiver_id, a.team_id as passer_team, b.team_id as receiver_team
from {{ ref('gold_pass_network') }} n
left join {{ ref('stg_players') }} a on a.match_id = n.match_id and a.player_id = n.passer_id
left join {{ ref('stg_players') }} b on b.match_id = n.match_id and b.player_id = n.receiver_id
where a.team_id is distinct from b.team_id or a.team_id is distinct from n.team_id
