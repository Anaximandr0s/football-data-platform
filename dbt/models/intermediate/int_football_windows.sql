-- Grain: one row per window per size (300 and 900 seconds) per match: the football windows of the macro
-- football_window with their bounds in ts (end exclusive), label and length. A half shorter than 45:00 has no
-- stoppage window; the stoppage window (45+, 90+) lasts until the end of its half, so it can be short or long.
with halves as (
    select match_id, 1 as period, p1_start_ts as start_ts, p1_end_ts + 1 as end_ts from {{ ref('stg_matches') }}
    union all
    select match_id, 2, p2_start_ts, p2_end_ts + 1 from {{ ref('stg_matches') }}
),

w as (
    select h.*, s.size, unnest(generate_series(0, 2700 // s.size)) as k
    from halves h cross join (values (300), (900)) s(size)
)

select
    match_id,
    size                                                          as window_size,
    (k + case when period = 2 then 2700 // size + 1 else 0 end)::int as window_index,
    period,
    k = 2700 // size                                              as is_stoppage,
    case when k = 2700 // size then cast(45 * period as varchar) || '+'
         else cast(45 * (period - 1) + k * size // 60 as varchar) || '-'
              || cast(45 * (period - 1) + (k + 1) * size // 60 as varchar) end as window_label,
    (start_ts + k * size)::int                                   as window_start_ts,
    (case when k = 2700 // size then end_ts else least(start_ts + (k + 1) * size, end_ts) end)::int as window_end_ts,
    (case when k = 2700 // size then end_ts else least(start_ts + (k + 1) * size, end_ts) end)
        - (start_ts + k * size)                                   as window_seconds
from w
where start_ts + k * size < end_ts
