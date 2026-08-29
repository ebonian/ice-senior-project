"""Swap-level loader for the B2 daily parquets.

The harness's `HourlySwapData` pre-buckets swaps by `dt.floor("h")`, which is
what forces finding H1 (see gate1/REPORT.md): the hour bucket a step reads is
the hour *after* the interval it is pricing. Mode-A replay works on real cycle
boundaries (mint at 05:02:06, burn at 07:02:08), not hour buckets, so it needs
the swaps as a flat time-ordered frame and slices them by timestamp.

Every column derivation here is copied from `HourlySwapData.from_raw_parquet`
so the two views agree swap-for-swap; `tests/test_fee_equivalence.py` asserts it.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

GATE1 = Path(__file__).resolve().parents[1]
DEFAULT_SWAP_DIR = GATE1 / "data" / "b2" / "swaps"


def load_swaps(
    start: datetime,
    end: datetime,
    swap_dir: Path = DEFAULT_SWAP_DIR,
    decimals0: int = 18,
    decimals1: int = 6,
) -> pd.DataFrame:
    """Flat, time-ordered swap frame over [start, end).

    Columns: ts, price (human ETH/USDC), volume_usd, pool_liquidity (raw v3
    units), v3_tick, amount0, amount1.
    """
    files = sorted(Path(swap_dir).glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no swap parquets under {swap_dir}")

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    if start_ts.tz is None:
        start_ts = start_ts.tz_localize("UTC")
    if end_ts.tz is None:
        end_ts = end_ts.tz_localize("UTC")

    keep = []
    for f in files:
        day = pd.Timestamp(f.stem).tz_localize("UTC")
        # A daily file can hold swaps for its own day only; keep the days that
        # intersect [start, end).
        if day + pd.Timedelta(days=1) <= start_ts or day >= end_ts:
            continue
        keep.append(f)
    if not keep:
        raise FileNotFoundError(f"no swap parquets covering {start_ts}..{end_ts} in {swap_dir}")

    df = pd.concat([pd.read_parquet(f) for f in keep], ignore_index=True)

    df["ts"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    # price = (sqrt_price_x96 / 2^96)^2 * 10^(d0-d1)   [same as the harness]
    sqrt_px96 = df["sqrt_price_x96"].apply(lambda x: int(str(x))).astype(float)
    df["price"] = (sqrt_px96 / (2**96)) ** 2 * 10 ** (decimals0 - decimals1)
    df["amount0"] = df["amount0"].apply(lambda x: int(str(x))).astype(float)
    df["amount1"] = df["amount1"].apply(lambda x: int(str(x))).astype(float)
    # USD notional = |amount1| / 10^d1, matching the harness. V3 charges the fee
    # on the *input* token, so on ETH->USDC swaps this is the output leg and is
    # low by exactly the fee (5 bps of 5 bps = 2.5e-7 of notional). Noted in the
    # audit; far below every Gate 1 tolerance.
    df["volume_usd"] = df["amount1"].abs() / 10**decimals1
    df["pool_liquidity"] = df["liquidity"].apply(lambda x: float(int(str(x))))
    df["v3_tick"] = df["tick"].astype(np.int64)

    df = df[(df["ts"] >= start_ts) & (df["ts"] < end_ts)]
    # log_index orders swaps inside a block; block_number orders blocks.
    sort_cols = [c for c in ("block_number", "log_index") if c in df.columns]
    df = df.sort_values(["ts"] + sort_cols, kind="mergesort").reset_index(drop=True)

    return df[["ts", "price", "volume_usd", "pool_liquidity", "v3_tick", "amount0", "amount1"]]


def slice_swaps(swaps: pd.DataFrame, t0: datetime, t1: datetime) -> pd.DataFrame:
    """Swaps in [t0, t1). Cycle boundaries, not hour buckets."""
    a = pd.Timestamp(t0)
    b = pd.Timestamp(t1)
    if a.tz is None:
        a = a.tz_localize("UTC")
    if b.tz is None:
        b = b.tz_localize("UTC")
    return swaps[(swaps["ts"] >= a) & (swaps["ts"] < b)]


def price_at(swaps: pd.DataFrame, t: datetime) -> float:
    """Last on-chain price at or before `t` (the pool's own mark)."""
    ts = pd.Timestamp(t)
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    prior = swaps[swaps["ts"] <= ts]
    if len(prior) == 0:
        return float(swaps["price"].iloc[0])
    return float(prior["price"].iloc[-1])


def continuity_report(swaps: pd.DataFrame, t0: datetime, t1: datetime) -> dict:
    """Gap check — §9's 'refuse to replay a window with gaps' risk control."""
    s = slice_swaps(swaps, t0, t1)
    if len(s) < 2:
        return {"n_swaps": len(s), "max_gap_s": None, "hours_covered": 0, "hours_expected": 0}
    gaps = s["ts"].diff().dt.total_seconds().dropna()
    hours = s["ts"].dt.floor("h").nunique()
    expected = int((pd.Timestamp(t1) - pd.Timestamp(t0)).total_seconds() // 3600) + 1
    return {
        "n_swaps": int(len(s)),
        "max_gap_s": float(gaps.max()),
        "median_gap_s": float(gaps.median()),
        "hours_covered": int(hours),
        "hours_expected": expected,
    }
