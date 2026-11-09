"""Map a wall-clock time to a NEAR block height using bracketed interpolation search."""
from __future__ import annotations

from datetime import datetime, timezone

from .client import Client

GENESIS_HEIGHT = 9_820_210            # first block of mainnet
GENESIS_TS = 1_595_350_551_591_948_000  # ns


def to_ns(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1_000_000_000)


def _ts(block: dict) -> int:
    return int(block["block"]["block_timestamp"])


def latest_height(client: Client) -> int:
    res = client.post("blocks", {"limit": 1, "desc": True})
    return int(res["blocks"][0]["block_height"])


def _block_near(client: Client, height: int) -> tuple[int, int]:
    """Timestamp of `height`, stepping forward over skipped heights. Returns (height, ts)."""
    for h in range(height, height + 20):
        b = client.block(h)
        if b:
            return h, _ts(b)
    raise RuntimeError(f"no block found near {height}")


_ANCHORS: dict[int, int] = {GENESIS_HEIGHT: GENESIS_TS}     # height -> ns, grows as the search learns


def _remember(h: int, t: int) -> None:
    _ANCHORS[h] = t


def height_at(client: Client, target_ns: int, latest: int | None = None, tolerance_ns: int = 3_000_000_000) -> int:
    """First-ish block at or after `target_ns` (within `tolerance_ns`).

    Every block looked up is remembered as an anchor, so later searches start from a tight bracket
    instead of the whole chain (about 6 calls instead of 35 once a few months are known).
    """
    latest = latest or latest_height(client)
    hi_h, hi_t = _block_near(client, latest)
    _remember(hi_h, hi_t)
    below = [(h, t) for h, t in _ANCHORS.items() if t <= target_ns]
    above = [(h, t) for h, t in _ANCHORS.items() if t >= target_ns]
    lo_h, lo_t = max(below, key=lambda x: x[1]) if below else (GENESIS_HEIGHT, GENESIS_TS)
    if above:
        hi_h, hi_t = min(above, key=lambda x: x[1])
    if target_ns <= GENESIS_TS:
        return GENESIS_HEIGHT
    if target_ns >= hi_t and not above:
        return hi_h
    for i in range(60):
        if i % 3 == 2 or hi_t == lo_t:          # bisection every third step guarantees convergence
            guess = (lo_h + hi_h) // 2
        else:
            guess = lo_h + int((target_ns - lo_t) * (hi_h - lo_h) / (hi_t - lo_t))
        guess = min(max(guess, lo_h + 1), hi_h - 1) if hi_h - lo_h > 1 else lo_h
        h, t = _block_near(client, guess)
        _remember(h, t)
        if abs(t - target_ns) <= tolerance_ns:
            return h
        if t < target_ns:
            lo_h, lo_t = h, t
        else:
            hi_h, hi_t = h, t
        if hi_h - lo_h <= 1:
            return hi_h
    return hi_h
