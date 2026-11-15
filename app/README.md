# app
| Folder | What | Required? |
|---|---|---|
| `streamlit/` | the MatchLens site: Live, Matches, Fan and Coach views, Behind the data ([guide](streamlit/README.md)) | **Yes** (FOO-06/07) |
| `api/` | FastAPI WebSocket gateway: Kafka (group `live-gateway`) → browser | Bonus |
| `web3d/` | `pitch.js`, the canvas pitch component used by the Streamlit pages | **Yes** |

Data flow of the bonus page: Kafka → `api` → WebSocket → `web3d`. Gold stats come from DuckDB through the API.
