# Requirements coverage

| Ref | Requirement | Type | Owner | Status | Proof |
|---|---|---|---|---|---|
| FOO-01 | A full match: 22 players, 1 position per second, at least 1,000 actions | OBL | ingestion | done (real data instead of generated: confirm with the professor) | `make data`: m001 22 players per second, 1,741 events; m002 1,878 events |
| FOO-02 | Live replay through Kafka at x1 to x60 | OBL | ingestion | done at x60 (x1 to x60 supported) | `make replay`: 100 s for m001, `make counts` |
| FOO-03 | Silver Iceberg table, grain player x second | OBL | Silver / Gold | todo | |
| FOO-04 | Gold per player: distance, sprints, max speed, actions by type | OBL | Silver / Gold | todo | |
| FOO-05 | Checks: inside the pitch, speed <= 40, 22 players per second | OBL | Silver / Gold | todo | rules listed in `silver-guide.md` |
| FOO-06 | Streamlit pitch with live positions and score | OBL | both | todo | |
| FOO-07 | Streamlit heatmap of a player and shot maps | OBL | both | todo | |
| FOO-08 | 5-minute rolling stats with Spark Structured Streaming | OPT | Silver / Gold | todo | |
| FOO-09 | Compare two matches, or cluster player profiles | OPT | Silver / Gold | data ready (m001, m002 in bronze) | |

Status: todo · in progress · done (with proof: command, file or screenshot).