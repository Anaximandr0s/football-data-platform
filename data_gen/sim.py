"""Synthetic match simulator (FOO-01): 22 players x 5400 s, plus ~1600 game actions."""
import numpy as np
import pandas as pd
from faker import Faker

from data_gen.common import MATCH_SECONDS, PITCH_L, PITCH_W

# 4-4-2, home attacks toward +x. (position, x, y)
FORMATION = [("GK", 5, 34)] + [("DF", 25, y) for y in (10, 26, 42, 58)] \
    + [("MF", 50, y) for y in (10, 26, 42, 58)] + [("FW", 72, y) for y in (24, 44)]
V_MAX = 9.6           # m/s = 34.6 km/h hard cap on a normal second
V_SPRINT = 9.9        # m/s = 35.6 km/h during sprint bursts
ACC_MAX = 3.5         # m/s change allowed per second


def build_players(match_id: str, rng: np.random.Generator, seed: int) -> pd.DataFrame:
    fake = Faker("en_GB")
    Faker.seed(seed)
    rows = []
    for side, prefix in (("HOME", "H"), ("AWAY", "A")):
        for i, (pos, _, _) in enumerate(FORMATION, start=1):
            rows.append((match_id, f"{prefix}{i:02d}", side, fake.name(), pos, i))
    return pd.DataFrame(rows, columns=["match_id", "player_id", "team_id", "name",
                                       "position", "shirt_number"])


def _base_positions() -> np.ndarray:
    home = np.array([[x, y] for _, x, y in FORMATION], dtype=float)
    away = home.copy()
    away[:, 0] = PITCH_L - away[:, 0]
    return np.vstack([home, away])  # (22, 2)


def simulate_tracking(match_id: str, players: pd.DataFrame, rng: np.random.Generator):
    n = MATCH_SECONDS
    base = _base_positions()
    pos = base.copy()
    vel = np.zeros((22, 2))
    sprint_left = np.zeros(22, dtype=int)
    wander = np.zeros((22, 2))
    ball = np.array([PITCH_L / 2, PITCH_W / 2])
    poss = 0  # 0 = HOME, 1 = AWAY
    P = np.zeros((n, 22, 2))
    S = np.zeros((n, 22))
    BALL = np.zeros((n, 2))
    POSS = np.zeros(n, dtype=int)
    for t in range(n):
        if rng.random() < 0.015:
            poss = 1 - poss
        goal_x = PITCH_L if poss == 0 else 0.0
        ball[0] += 0.04 * (goal_x - ball[0]) + rng.normal(0, 4.0)
        ball[1] += 0.05 * (PITCH_W / 2 - ball[1]) + rng.normal(0, 3.5)
        ball = np.clip(ball, [0, 0], [PITCH_L, PITCH_W])
        shift = 0.40 * (ball[0] - PITCH_L / 2)
        wander = 0.85 * wander + rng.normal(0, 2.0, size=(22, 2))
        target = base + wander
        target[:, 0] += shift * np.where(np.arange(22) % 11 == 0, 0.2, 1.0)  # GK moves less
        target[:, 1] += 0.15 * (ball[1] - PITCH_W / 2)
        want = (target - pos) * 0.55
        start = (sprint_left == 0) & (rng.random(22) < 0.006)
        sprint_left[start] = rng.integers(4, 8, size=int(start.sum()))
        unit = (target - pos) / np.maximum(np.linalg.norm(target - pos, axis=1, keepdims=True), 1e-9)
        want = np.where((sprint_left > 0)[:, None], unit * 8.2, want)  # burst toward target (~29 km/h)
        vmax = np.where(sprint_left > 0, V_SPRINT, V_MAX)
        sprint_left = np.maximum(sprint_left - 1, 0)
        dv = want - vel
        dn = np.linalg.norm(dv, axis=1, keepdims=True)
        dv = np.where(dn > ACC_MAX, dv / np.maximum(dn, 1e-9) * ACC_MAX, dv)
        vel = vel + dv
        sp = np.linalg.norm(vel, axis=1, keepdims=True)
        vel = np.where(sp > vmax[:, None], vel / np.maximum(sp, 1e-9) * vmax[:, None], vel)
        new = np.clip(pos + vel, [0, 0], [PITCH_L, PITCH_W])
        S[t] = np.linalg.norm(new - pos, axis=1) * 3.6 if t > 0 else 0.0
        pos = new
        P[t], BALL[t], POSS[t] = pos, ball, poss
    ids = players["player_id"].to_numpy()
    df = pd.DataFrame({
        "match_id": match_id,
        "player_id": np.tile(ids, n),
        "ts": np.repeat(np.arange(n), 22),
        "x": P.reshape(-1, 2)[:, 0].round(2),
        "y": P.reshape(-1, 2)[:, 1].round(2),
        "speed_kmh": S.reshape(-1).round(2),
    })
    return df, P, BALL, POSS


def simulate_events(match_id, players, P, BALL, POSS, rng, n_events=1600):
    n = P.shape[0]
    ids = players["player_id"].to_numpy()
    team_of = players["team_id"].to_numpy()
    kinds = rng.choice(["pass", "tackle", "shot", "foul", "corner"], size=n_events,
                       p=[0.74, 0.12, 0.05, 0.06, 0.03])
    ts = np.sort(rng.integers(1, n - 3, size=n_events))
    # shots are placed when the ball is in the attacking third of the team in possession
    atk = np.where(POSS == 0, BALL[:, 0] > 70, BALL[:, 0] < 35)
    atk_ts = np.flatnonzero(atk)
    rows = []
    for k, (kind, t) in enumerate(zip(kinds, ts, strict=True), start=1):
        if kind == "shot" and len(atk_ts):
            t = int(rng.choice(atk_ts[atk_ts < n - 3]))
        t = int(t)
        side = POSS[t] if kind != "tackle" else 1 - POSS[t]
        mine = np.flatnonzero(np.arange(22) // 11 == side)
        d = np.linalg.norm(P[t, mine] - BALL[t], axis=1)
        w = np.exp(-d / 12.0)
        who = int(rng.choice(mine, p=w / w.sum()))
        x0, y0 = P[t, who]
        x1, y1, outcome, etype = x0, y0, "ok", kind
        if kind == "pass":
            others = mine[mine != who]
            dd = np.linalg.norm(P[t, others] - P[t, who], axis=1)
            ww = np.exp(-dd / 20.0)
            to = int(rng.choice(others, p=ww / ww.sum()))
            x1, y1 = P[min(t + 2, n - 1), to]
            outcome = "successful" if rng.random() < 0.82 else "unsuccessful"
        elif kind == "shot":
            gx = PITCH_L if side == 0 else 0.0
            x1, y1 = gx, rng.uniform(30.3, 37.7)
            r = rng.random()
            outcome = "goal" if r < 0.09 else "saved" if r < 0.40 else "blocked" if r < 0.60 else "off_target"
            if outcome == "goal":
                etype = "goal"
        elif kind == "corner":
            x0 = PITCH_L if side == 0 else 0.0
            y0 = float(rng.choice([0.0, PITCH_W]))
            x1, y1 = x0, y0
        elif kind in ("tackle", "foul"):
            outcome = "won" if kind == "tackle" and rng.random() < 0.6 else "committed" if kind == "foul" else "lost"
        rows.append((match_id, f"{match_id}-e{k:05d}", t, ids[who], team_of[who], etype,
                     round(float(x0), 2), round(float(y0), 2), round(float(x1), 2),
                     round(float(y1), 2), outcome))
    from data_gen.common import EVENT_COLS
    return pd.DataFrame(rows, columns=EVENT_COLS)


def simulate_match(match_id: str, seed: int):
    rng = np.random.default_rng(seed)
    players = build_players(match_id, rng, seed)
    tracking, P, BALL, POSS = simulate_tracking(match_id, players, rng)
    events = simulate_events(match_id, players, P, BALL, POSS, rng)
    return players, tracking, events
