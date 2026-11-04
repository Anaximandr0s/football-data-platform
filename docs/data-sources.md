# Data sources

All data comes from **SkillCorner open data** (MIT licence, <https://github.com/SkillCorner/opendata>):
real broadcast-tracking data of A-League matches (season 2024/2025). Credit SkillCorner in the app and the report.
The brief says "generate"; we use open data instead and convert it with `ingestion/ingest_foot.py`
(confirm with the professor, and say it in the report).

| Our id | SkillCorner id | Match | Role |
|---|---|---|---|
| `m001` | 1874553 | Brisbane Roar FC 2-3 Adelaide United Football Club | main match |
| `m002` | 1925299 | Brisbane Roar FC 0-1 Perth Glory Football Club | second match for FOO-09 (same home club) |

Why these two: the platform needs a 105 x 68 pitch (8 of the 20 matches have another size). m001 was the first one
validated end to end, and its derived goals equal the real score. m002 has the best tracking coverage among the
matches with a valid pitch (78.2%).

## What the raw files contain

- `<id>_match.json`: lineups, teams, league, score, periods, pitch size.
- `<id>_tracking_extrapolated.jsonl`: one line per frame, 10 frames per second, ball (x, y, z) and the players, centred coordinates.
- `<id>_dynamic_events.csv`: more than 300 columns; four families (possessions, off-ball runs, engagements, passing options).
  We keep possessions ending in a pass or shot, and engagements.

The conversion to our tables is described in [`contrat_donnees.md`](contrat_donnees.md). Nothing is cleaned at ingestion.

## Known limits (state them in the report)

- **Gaps.** In m001 only 73.4% of the seconds have data; the 20 matches range from 66% to 81%. In a gap second the frame keeps its clock
  and period but has no player and no ball. Only 55 of the 1,602 gap seconds of m001 have a team in possession, and the tracked time with
  possession (about 54.8 min) matches the ball-in-play time of the match file (54.7 min). Gap frames almost never have a camera area
  (3 of 1,602) and about half of the plays that restart after a gap are set pieces. Reading: mostly dead-ball stoppages without a
  broadcast view of the pitch. This is an interpretation, not a statement from SkillCorner.
- **Consequence.** Distance and sprints cover tracked time only (about three quarters of the match). The live pitch pauses in gaps
  (the longest, 143 s, lasts about 2.4 s at x60).
- A match lasts about 100 minutes (stoppage time), not 90: `ts` runs to about 6,000.
- Broadcast tracking is computer-vision based (about 97% identity accuracy): expect small errors. 0.75% of the m001 positions lie outside the pitch.
- Speed is not provided: we derive it from positions one second apart, so it under-estimates short peaks.
- No corner events in this source; shot outcome is not detailed (a `goal` is derived from the score).
- Attack directions swap at half-time and are not normalised in bronze.

## Add another match

```bash
python -m ingestion.download_foot --list          # ids available in the repository
make data MATCH=m003 SC_ID=<id>                   # download + convert (the pitch must be 105 x 68)
make replay MATCH=m003
make check MATCH=m003
```
Pin the ids you use: never pick a match at random for a deliverable. Read `manifest.json` after converting:
22 players per second, goals equal to the real score.

## Where files live

```
data/raw/skillcorner/<id>/     downloaded files (git-ignored)
data/prepared/<match_id>/      players, tracking, events, ball, matches (.parquet) + manifest.json (git-ignored)
s3://bronze/...                bronze tables in MinIO (see the contract)
```