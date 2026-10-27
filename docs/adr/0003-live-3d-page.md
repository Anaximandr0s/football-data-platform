# ADR 0003: 3D live page in addition to Streamlit
- **Status:** proposed
- **Context:** FOO-06/07 explicitly require Streamlit + mplsoccer. A 3D page is a bonus, not a replacement.
- **Decision:** keep Streamlit for the mandatory requirements. Build `app/web3d` (Three.js) fed by `app/api` (FastAPI WebSocket, Kafka group `live-gateway`). Embed it in Streamlit with an iframe if desired.
- **Justification for the report:** browser rendering of 22 moving players at high refresh rate, which Streamlit reruns cannot do smoothly.
