# app

| Folder | What |
|---|---|
| `streamlit/` | the MatchLens site: Live, Matches, Fan and Coach views, Behind the data ([guide](streamlit/README.md)), `make app` |
| `pitch/` | `pitch.js`, the canvas pitch component the Streamlit pages load (no build step, [details](pitch/README.md)) |
| `api/` | the Control Center: the architecture with live status, start and stop a replay, performance ([guide](api/README.md)), `make demo` |

The site reads Gold (DuckDB, read-only) and, on the Live page, the Kafka topics. The Control Center reads Prometheus,
Dagster, Gold and Kafka, and its only actions are starting and stopping a replay.
