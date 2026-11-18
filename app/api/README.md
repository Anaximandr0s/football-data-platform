# MatchLens Control Center

One local page that runs the demo with no typed command: the architecture of the platform as a diagram with a status
light on each box (click a box: its role, live numbers, buttons to its real tool), the running containers, a match to
play live, and the performance and quality numbers.

```bash
make demo          # starts everything the demo needs, then http://localhost:8000
make demo-reset    # replays the 4 matches once at x60, one after the other (Dagster rebuilds each)
```

## How it works

| File | Role |
|---|---|
| `core.py` | the rules, pure: which replay may start, where it starts, its football clock, each box's light, the links, the texts |
| `services.py` | the edges: Prometheus, Dagster (GraphQL), the Gold file (read-only), Kafka, the producer processes |
| `main.py` | FastAPI: read-only `GET /api/*`, and the only two actions, `POST /api/replay/start` and `/api/replay/stop` |
| `static/` | one HTML page, its CSS and JavaScript (no build step), Tabler icons (MIT, `static/icons/LICENSE`) |

- **Two actions only.** A replay starts when the match is in Gold's library and prepared, the speed is a whole number
  from 1 to 60 (the page offers x1, x5, x10), the start is inside the match, it is not already playing, and fewer than
  2 replays play. Checked under one lock, so two clicks cannot pass the limit together. Everything else is read-only.
- **Progress is what Kafka received.** A consumer reads the replay topics and keeps, per replay, the last match second
  actually sent: a producer slower than its target speed shows its real position.
- **"30 s before the first goal"** starts 30 s before the second the ball was in the goal (`gold_events.goal_ts`).
- **Status lights and numbers** come from Prometheus (the same queries as the Grafana dashboards); the container list
  from cAdvisor's metrics: no Docker socket. A container cAdvisor does not see is shown "not running".
- **The diagram** is SVG written in `static/index.html`, with its icons inlined, so the exported SVG and PNG (2x) stand
  alone for slides.
- **Port 127.0.0.1:8000 only** (`CONTROL_PORT`). No login: anyone on this machine can start a replay, nothing else.

## Tests

`python -m pytest tests/api`: the whitelist (unknown match, bad speed, bad start, a second replay of a match, a third
replay, any other route), the start presets, the clock, the lights, the links and the payloads, with fake services.

## Limits

- The containers popup cannot tell a crashed container from a stopped one (cAdvisor sees only running containers).
- The links open on the machine running the platform (`localhost`).
- A replay started here stops when the Control Center restarts (its producer is a child process).
