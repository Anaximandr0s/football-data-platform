# MatchLens (Streamlit + mplsoccer)

One website, the app map of [`docs/product.md`](../../docs/product.md) section 8: Home, then the sections LIVE, MATCHES,
FAN VIEW or COACH VIEW (the one chosen on Home), and BEHIND THE DATA. The Gold pages compute nothing that Gold does not
already hold: they select, filter and draw, and open the data read-only. The Live match page rebuilds the score,
possession and positions from the replayed Kafka messages.

```mermaid
flowchart LR
    G[(data/football.duckdb<br/>Gold tables)] -->|short read-only queries| D[data.py]
    Q[(data/soda/*.json)] --> D
    R[app.py: router<br/>menu, view, match] --> P[pages/*.py]
    S[sitemap.py<br/>pages, questions, menu] --> R
    D --> P
    V[viz.py<br/>mplsoccer figures] --> P
```

## Run it

Needs `make silver` and `make gold` done (`make soda` fills the quality page):

```bash
make app            # builds the image, starts the dashboard: http://localhost:8501
make app-stop       # stops it  (`make down` stops it too)
```

Without Docker: `pip install -r requirements.txt`, then `streamlit run app/streamlit/app.py`. Without any Gold file the
pages say what to run instead of crashing.

## Pages

Home asks for a match and a view; the menu then shows that view's section, and the sidebar keeps a view switch and the
match picker. The view and the match are plain session keys (`view`, `match_id`), so they follow the visitor from page
to page. A page marked "coming soon" states its question and the build step (product.md, section 12) that will add it.

| Section | Page | Reads | Now |
|---|---|---|---|
| | Home | `gold_match_library` | wordmark, match cards (teams, score, date, tracked share), "I am a Fan / I am a Coach" |
| LIVE | Live match | Kafka topics `foot-*`, through one background consumer | the match being replayed (`make replay`): pitch with the 22 players (lighter = estimated position) and the ball, score from goal events, clock and period, possession bar, last goal / shot / tackle / foul, width and length of each team for the current second, "No tracking: camera off the pitch" during a camera gap, a box for the 5-minute stats of FOO-08. Redrawn about once per second (FOO-06) |
| MATCHES | Match library | `gold_match_library` | every stored match, newest first; selecting a row makes it the match of every page |
| MATCHES | Replay | | coming soon (step 7) |
| MATCHES | Compare matches | `gold_team_match_stats` | two or more matches side by side at team level (FOO-09) |
| FAN VIEW | Match story | `gold_team_match_stats` | scoreboard and side-by-side team numbers (the former overview) |
| FAN VIEW | Squad | | coming soon (step 3) |
| FAN VIEW, COACH VIEW | Player page | `gold_player_match_stats`, `gold_zone_occupancy` | pick a team and a player: key numbers, position heatmap (FOO-07), ranking of the match on any metric |
| COACH VIEW | Team analysis | `gold_shots`, `gold_pass_network`, `gold_player_match_stats` | shot map of both teams with filters and a shot table; pass network of one team (FOO-07) |
| COACH VIEW | Physical & fatigue | `gold_player_5min` | distance and sprint seconds per 5 minutes of one player, with the coverage of each window |
| COACH VIEW | Event explorer | | coming soon (step 5) |
| BEHIND THE DATA | Data quality | `data/soda/silver.json`, `gold.json` | passed / failed / warnings / errors of the last `make soda` per layer, and the list of checks (FOO-05) |
| BEHIND THE DATA | Pipeline & lineage, Sources & limits | | coming soon (step 8) |

Look: a stadium at night (`.streamlit/config.toml`, colours checked for contrast: body text 16:1, white on the primary
green 5.0:1); `sitemap.style()` holds the few shared classes, and the charts use the same background (`viz.BG`).

## Reading the graphics

- **Frame of the Live match page.** It draws the replayed positions as the camera sees them: teams switch ends at
  half-time, and arrows show the direction of attack of the current period.
- **Frame.** Every Gold graphic uses the Silver frame: the pitch is 105 x 68 m, **HOME always attacks to the right** and AWAY to
  the left, in both halves. An AWAY player's heatmap therefore looks mirrored compared with a TV picture.
- **Colours.** Team colours are the kit colours of the source. A colour that is too dark for the dark pitch (m001's HOME is
  `#363636`) or two similar colours are replaced by fixed ones (red and blue).
- **Approximate numbers.** Distances, speeds and sprints cover tracked seconds only (about 3/4 of a match) and come from 1 Hz
  positions: they under-estimate real values. Compare players inside one match. Player ids are local to a match, so the
  compare page works on teams, not on players.
- **Credit.** SkillCorner open data, shown on every page.

## Files

| File | Role |
|---|---|
| `app.py` | the router: `st.navigation` menu for the chosen view, the sidebar (view switch, match picker), the move to a view's first page |
| `sitemap.py` | every page with its section, question and persona; the menu per view; the page header and the "coming soon" box. Pure data, tested without Streamlit |
| `pages/*.py` | the pages |
| `data.py` | reading Gold (cached for a minute), the current match, the match library, the Soda result reader, shared texts |
| `viz.py` | the figures: zone heatmap, shot map, pass network, ranking bars, live pitch (pure functions, tested without Streamlit) |
| `live.py` | the live state of a replayed match: `apply(state, table, record, kafka_ms)` returns a new state, plus the readers (score, possession, clock, status, team shape, event line). Pure, tested without Kafka |
| `live_feed.py` | the single Kafka consumer of the app (a thread created once by `st.cache_resource`), holding the latest state per match |
| `Dockerfile`, `requirements.txt` | the image of `make app` (the repository is mounted read-only, nothing is copied in) |

Settings by environment variable: `GOLD_DUCKDB_PATH` (default `data/football.duckdb`), `GOLD_PARQUET_DIR` (read
`<table>.parquet` files from a local folder instead, e.g. a copy of `s3://gold`), `SODA_OUT_DIR`, `APP_PORT` (compose),
`KAFKA_BOOTSTRAP` (Live match page: `kafka:9092` inside Docker, set by compose; `localhost:29092` outside).

The live consumer reads every topic from the beginning with its own group and commits nothing. A topic keeps every replay of
the last 7 days, so each message is judged by its Kafka time against the start of the latest replay of its match (the
time of its `matches` message): older replays are dropped, a page opened in the middle of a replay still has the score
from the kick-off, and the order in which the topics are read does not matter. Reading that history takes time after the
`app` container starts: 537,939 messages (every replay still in the topics) in at most 16 s, measured on 2026-11-15.

The DuckDB file is opened for the time of one query and closed at once: DuckDB allows a single writer, so a connection kept
open by the dashboard would block the next `make gold`.

## Tests

`tests/app/`: every page runs headless (Streamlit `AppTest`) on a real Gold file built by dbt from the tiny fixture, plus the
case "Gold does not exist yet" and the colour rules; `test_site.py` checks the menu of each view, that every page has a
file, and through the router that choosing a view asks for its first page and that pages keep the view and the match
(`python -m pytest tests/app`). After its first run `AppTest` reruns only the page, not the router, so the move to a
view's first page and the sidebar view switch are checked in a browser instead (Playwright, see the step 2 proof). The graphics were also rendered on the real
m001 data and looked at: the shot map shows HOME's 2 goals at the right goal and AWAY's 3 at the left one (final score 2-3),
and the pass network puts AWAY's goalkeeper near x = 100, as expected for a team attacking to the left.

## Not built (yet)

- The 5-minute live stats of the Live match page (FOO-08): a placeholder box until the streaming job writes `foot-live-stats`.
- The bonus 3D page and the FastAPI gateway are the other folders of `app/`.
- Clustering of player profiles (FOO-09, optional): only the team-level comparison exists.
- The `app` container and the browser rendering were not run here (no Docker, no browser in the development sandbox): the
  pages were run headless and the figures rendered to images.
