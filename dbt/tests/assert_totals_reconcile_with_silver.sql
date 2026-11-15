-- Failing rows = an aggregate that lost or invented something: passes, passes with a receiver, tracked seconds.
with silver as (
    select match_id,
           count(*) filter (where type = 'pass') as passes,
           count(*) filter (where type = 'pass' and receiver_id is not null) as passes_with_receiver
    from {{ ref('stg_events') }} group by match_id
),
secs as (select match_id, count(*) as tracked_seconds from {{ ref('stg_tracking') }} group by match_id),
players as (
    select match_id, sum(passes) as passes, sum(passes_received) as received, sum(tracked_seconds) as tracked_seconds
    from {{ ref('gold_player_match_stats') }} group by match_id
),
network as (select match_id, sum(passes) as passes from {{ ref('gold_pass_network') }} group by match_id),
zones as (select match_id, sum(seconds) as tracked_seconds from {{ ref('gold_zone_occupancy') }} group by match_id),
win as (select match_id, sum(tracked_seconds) as tracked_seconds from {{ ref('gold_player_5min') }} group by match_id),
teams as (select match_id, sum(passes) as passes from {{ ref('gold_team_match_stats') }} group by match_id)
select s.match_id, s.passes, s.passes_with_receiver, p.passes as player_passes, p.received, t.passes as team_passes,
       n.passes as network_passes, sec.tracked_seconds, p.tracked_seconds as player_seconds,
       z.tracked_seconds as zone_seconds, w.tracked_seconds as window_seconds
from silver s
left join players p using (match_id) left join teams t using (match_id) left join network n using (match_id)
left join secs sec using (match_id) left join zones z using (match_id) left join win w using (match_id)
where p.passes != s.passes or t.passes != s.passes
   or p.received != s.passes_with_receiver or n.passes != s.passes_with_receiver
   or p.tracked_seconds != sec.tracked_seconds or z.tracked_seconds != sec.tracked_seconds
   or w.tracked_seconds != sec.tracked_seconds
