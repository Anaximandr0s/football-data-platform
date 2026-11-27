"""Grain: one row per tracked second per match (S1). Each cell centre of a 1 m grid over the 105 x 68 pitch belongs to
the nearest player present that second, detected or not; home_share = cells of HOME / all cells (AWAY = 1 - home_share).
"""

import numpy as np
import pandas as pd

CELL_M = 1.0  # docs/product.md S1: 1 m, 2 m only if a match takes more than about 60 s
PITCH = (105.0, 68.0)


def cell_centres(cell_m: float = CELL_M) -> tuple[np.ndarray, np.ndarray]:
    gx, gy = np.meshgrid(np.arange(cell_m / 2, PITCH[0], cell_m), np.arange(cell_m / 2, PITCH[1], cell_m))
    return gx.ravel(), gy.ravel()


def home_share(x: np.ndarray, y: np.ndarray, is_home: np.ndarray, cells: tuple[np.ndarray, np.ndarray]) -> float:
    cx, cy = cells
    nearest = ((cx[:, None] - x[None, :]) ** 2 + (cy[:, None] - y[None, :]) ** 2).argmin(axis=1)
    return float(is_home[nearest].mean())


def per_second(trk: pd.DataFrame, cells: tuple[np.ndarray, np.ndarray]) -> pd.DataFrame:
    rows = [
        (
            match_id,
            ts,
            r["period"].max(),
            len(r),
            int(r["is_detected"].sum()),
            home_share(r["x"].to_numpy(), r["y"].to_numpy(), (r["team_id"] == "HOME").to_numpy(), cells),
        )
        for (match_id, ts), r in trk.groupby(["match_id", "ts"])
    ]
    out = pd.DataFrame(rows, columns=["match_id", "ts", "period", "players", "detected_players", "home_share"])
    return out.astype({"ts": "int32", "period": "int32", "players": "int64", "detected_players": "int64"})


def model(dbt, session):
    dbt.config(materialized="table")
    trk = (
        dbt.ref("stg_tracking")
        .project("match_id, ts, period, team_id, x, y, coalesce(is_detected, false) as is_detected")
        .df()
    )
    return per_second(trk, cell_centres())
