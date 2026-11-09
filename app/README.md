# app
| Folder | What | Required? |
|---|---|---|
| `streamlit/` | dashboard on Gold: heatmap, shot map, pass network, compare page, quality page (mplsoccer) ([guide](streamlit/README.md)); live pitch + score still to do | **Yes** (FOO-06/07) |
| `api/` | FastAPI WebSocket gateway: Kafka (group `live-gateway`) → browser | Bonus |
| `web3d/` | 3D live page (Three.js): moving players, ball, score, live stats panel | Bonus |

Data flow of the bonus page: Kafka → `api` → WebSocket → `web3d`. Gold stats come from DuckDB through the API.
