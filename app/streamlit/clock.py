"""clock.py: the football clock fans see on TV, from a replay second ts and its period. Used by every page that shows
a time (Live, Match story, Player page, Team analysis; later Replay).

ts counts seconds from the first kick-off without stopping, so it includes the first-half stoppage time and the
half-time pause. The football clock restarts the second half at 45:00 from its own kick-off (p2_start_ts):
  period 1: minute 1 = 0:00-0:59 ... minute 45, then 45+1, 45+2 ...
  period 2: minute 46 = the first minute after the second kick-off ... minute 90, then 90+1 ...
p1_start_ts and p2_start_ts are the first second of each period in the data; for m001 and m002 they are exactly the
kick-off frames of match.json (m001: frame 29000 = ts 2899).
"""

HALF_MINUTES = 45


def period_of(ts: int, p2_start_ts: int | None) -> int:
    """The period of a second when the row does not say it."""
    return 2 if p2_start_ts is not None and ts >= p2_start_ts else 1


def minute(ts: int, period: int | None, p1_start_ts: int, p2_start_ts: int | None) -> tuple[int, int]:
    """(minute, added minutes): (6, 0) for 6', (45, 2) for 45+2', (90, 1) for 90+1'."""
    period = period if period in (1, 2) else period_of(ts, p2_start_ts)
    start = p2_start_ts if period == 2 and p2_start_ts is not None else p1_start_ts
    base, limit = (HALF_MINUTES, 2 * HALF_MINUTES) if period == 2 else (0, HALF_MINUTES)
    m = base + max(0, int(ts) - int(start)) // 60 + 1
    return (limit, m - limit) if m > limit else (m, 0)


def label(ts: int, period: int | None, p1_start_ts: int, p2_start_ts: int | None, mark: str = "'") -> str:
    """ "6'", "45+2'", "90+1'"."""
    m, added = minute(ts, period, p1_start_ts, p2_start_ts)
    return f"{m}+{added}{mark}" if added else f"{m}{mark}"


def running(ts: int, period: int | None, p1_start_ts: int, p2_start_ts: int | None) -> str:
    """The running clock: "31:44", "47:05", or "45:00 +1:12" in stoppage time."""
    period = period if period in (1, 2) else period_of(ts, p2_start_ts)
    start = p2_start_ts if period == 2 and p2_start_ts is not None else p1_start_ts
    base, limit = (HALF_MINUTES, 2 * HALF_MINUTES) if period == 2 else (0, HALF_MINUTES)
    seconds = base * 60 + max(0, int(ts) - int(start))
    over = seconds - limit * 60
    if over > 0:
        return f"{limit}:00 +{over // 60}:{over % 60:02d}"
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def span(ts_start: int, ts_end: int, p1_start_ts: int, p2_start_ts: int | None) -> str:
    """The minutes of a time window [ts_start, ts_end): "57-62", "45+1-47"."""
    a = label(ts_start, None, p1_start_ts, p2_start_ts, mark="")
    b = label(max(ts_start, ts_end - 1), None, p1_start_ts, p2_start_ts, mark="")
    return a if a == b else f"{a}-{b}"


def axis_ticks(p1_start_ts: int, p2_start_ts: int | None, end_ts: int) -> list[tuple[float, str]]:
    """Positions (minutes of ts) and labels of a timeline axis drawn in ts: 0', 15', 30', then 45' at the second
    kick-off, 60', 75', 90'. No 45' tick in the first half: it would sit a few minutes from the second one."""
    ticks = [
        ((p1_start_ts + 60 * m) / 60, f"{m}'")
        for m in (0, 15, 30)
        if p2_start_ts is None or p1_start_ts + 60 * m < p2_start_ts
    ]
    if p2_start_ts is not None:
        ticks += [
            ((p2_start_ts + 60 * (m - 45)) / 60, f"{m}'")
            for m in (45, 60, 75, 90)
            if p2_start_ts + 60 * (m - 45) <= end_ts
        ]
    return ticks


# ---------------------------------------------------------------- football windows (docs/product.md, section 2)
# 5- and 15-minute windows restart at each kick-off: 0-5' ... 40-45', then one stoppage window 45+ (as long as the
# first-half stoppage time), 45-50' ... 85-90', then 90+. The dbt macro football_window and Spark Streaming
# use the same rule; tests/dbt checks that dbt and this function agree.
REGULAR_SECONDS = HALF_MINUTES * 60


def regular_windows(size: int) -> int:
    """Regular windows per half: 9 of 5 minutes, 3 of 15 minutes."""
    return REGULAR_SECONDS // size


def window_index(ts: int, period: int | None, p1_start_ts: int, p2_start_ts: int | None, size: int = 300) -> int:
    """0..8 then 9 (45+) in the first half, 10..18 then 19 (90+) in the second; 0..2, 3, 4..6, 7 for 15 minutes."""
    period = period if period in (1, 2) else period_of(ts, p2_start_ts)
    start = p2_start_ts if period == 2 and p2_start_ts is not None else p1_start_ts
    k = min(max(0, int(ts) - int(start)) // size, regular_windows(size))
    return k + (regular_windows(size) + 1 if period == 2 else 0)


def window_label(index: int, size: int = 300) -> str:
    """ "0-5", "40-45", "45+", "45-50", "90+" (15 minutes: "0-15", "45+", "75-90", "90+")."""
    n = regular_windows(size)
    period, k = (2, index - n - 1) if index > n else (1, index)
    if k == n:
        return f"{HALF_MINUTES * period}+"
    first = HALF_MINUTES * (period - 1) + k * size // 60
    return f"{first}-{first + size // 60}"


def windows(p1_start_ts: int, p1_end_ts: int, p2_start_ts: int, p2_end_ts: int, size: int = 300) -> list[tuple]:
    """Every window of a match: (index, period, label, start_ts, end_ts exclusive). A half that ends before 45:00 has
    no stoppage window; the stoppage window lasts until the end of the half."""
    out = []
    for period, start, end in ((1, p1_start_ts, p1_end_ts + 1), (2, p2_start_ts, p2_end_ts + 1)):
        for k in range(regular_windows(size) + 1):
            first = start + k * size
            if first >= end:
                break
            last = end if k == regular_windows(size) else min(first + size, end)
            index = k + (regular_windows(size) + 1 if period == 2 else 0)
            out.append((index, period, window_label(index, size), first, last))
    return out
