-- Grain: one row per stored match (Match library, Home): teams, colours, score, kick-off, competition and how much of
-- the match the camera tracked. tracked_share = distinct tracked seconds / seconds of the two periods.
with tracked as (
    select match_id, count(distinct ts) as tracked_seconds
    from {{ ref('stg_tracking') }}
    group by 1
)

select
    m.match_id,
    m.home_team, m.away_team, m.home_team_short, m.away_team_short, m.home_color, m.away_color,
    m.home_score, m.away_score,
    m.kickoff_utc,
    cast(cast(m.kickoff_utc as timestamptz) at time zone 'UTC' as date) as match_date,
    m.competition, m.season, m.round, m.stadium,
    (m.p1_end_ts - m.p1_start_ts + 1) + (m.p2_end_ts - m.p2_start_ts + 1)  as match_seconds,
    coalesce(t.tracked_seconds, 0)                                       as tracked_seconds,
    round(coalesce(t.tracked_seconds, 0)
          / ((m.p1_end_ts - m.p1_start_ts + 1) + (m.p2_end_ts - m.p2_start_ts + 1)), 4) as tracked_share
from {{ ref('stg_matches') }} m
left join tracked t using (match_id)
