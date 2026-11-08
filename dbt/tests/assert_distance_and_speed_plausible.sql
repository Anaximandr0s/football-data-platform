-- Failing rows = a negative distance, a speed above the plausibility limit, or a sprint effort count above sprint seconds.
select match_id, player_id, distance_m, max_speed_kmh, sprint_count, sprint_seconds
from {{ ref('gold_player_match_stats') }}
where distance_m < 0 or max_speed_kmh > {{ var('max_speed_kmh') }} or sprint_count > sprint_seconds
