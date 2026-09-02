#!/usr/bin/env python3
"""E007 — the six pre-named causal signals (memo M001 §5, pre-registered).

Every signal value at hour boundary t is a function ONLY of data with
timestamp < t (contract 4 tests this by recomputation from truncated data).
Conventions shared with E006: the hour grid is stage 1's (`hour_epoch` in
e006/out/stage1_hours_w<W>.csv); per-hour quantities indexed h are known at
hour h's END, so the signal deciding hour t may use quantities of hours
<= t-1 (a `shift(1)` on the hour series).

  C1  EWMA(halflife λ) of stage-1 freshly-centered hourly payoff  (enter >= θ)
  C2  EWMA(λ) of log intra-hour swap-stream RV                     (enter <= θ)
  C3  dow×hod cell mean of hourly payoff, tune-window-estimated,
      shrunk toward the tune-window global mean with weight κ      (enter >= θ)
  C4  Binance ETHUSDT last-N-minute 1m-close realized vol          (enter <= θ)
  C5  C2 on jump-robust bipower variation                          (enter <= θ)
  C6  C1 AND C3 (λ, κ inherited; thresholds θ1, θ2 tuned)

NaN signal (warmup) => out of position.
"""

from __future__ import annotations

import gzip
import sys
from pathlib import Path

import numpy as np
import pandas as pd

E007 = Path(__file__).resolve().parent
BMS = E007.parent
for p in (BMS / "gate1", BMS / "e003", BMS / "e006"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import race     # noqa: E402

AUG1_EPOCH = 1785542400          # 2026-08-01 00:00:00 UTC — the held-out wall
EWMA_HALFLIVES = (2, 4, 8, 16, 24)
SEASONAL_KAPPAS = (0, 8, 32)
BINANCE_LOOKBACKS_MIN = (15, 30, 60)
THETA_DECILES = tuple(range(10, 100, 10))    # P10..P90, tune-window quantiles
BINANCE_CSV = E007 / "data" / "binance_ethusdt_1m.csv.gz"


def load_hours(w: int) -> pd.DataFrame:
    """E006 stage-1 per-hour frame for width w (committed artifact)."""
    return pd.read_csv(BMS / "e006" / "out" / f"stage1_hours_w{w}.csv")


def hourly_rv_bv(hs: np.ndarray, swaps: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Per-hour swap-stream realized vol and (jump-robust) bipower vol.

    rv[h] = sqrt(sum of squared swap-to-swap log returns inside hour h)
            (E006 signals.py boundary convention: the return connecting the
            previous hour's last swap into this hour's first swap counts
            toward this hour)
    bv[h] = sqrt((pi/2) * sum |r_i||r_{i-1}| over consecutive return pairs
            entirely inside hour h)  — Barndorff-Nielsen–Shephard bipower.
    """
    ts = swaps["timestamp"].to_numpy(np.int64)
    logp = np.log(swaps["price"].to_numpy(np.float64))
    r = np.diff(logp)                       # r[i]: return into swap i+1
    d2 = np.concatenate([[0.0], r ** 2])
    bp = np.concatenate([[0.0, 0.0], np.abs(r[1:]) * np.abs(r[:-1])])
    cs2 = np.concatenate([[0.0], np.cumsum(d2)])
    csb = np.concatenate([[0.0], np.cumsum(bp)])
    cuts = np.searchsorted(ts, np.concatenate([hs, [hs[-1] + 3600]]), side="right")
    rv = np.sqrt(cs2[cuts[1:]] - cs2[cuts[:-1]])
    # bp[i] pairs returns (i-2 -> i-1) and (i-1 -> i): both inside the hour only
    # if swap i-2 is already past the cut, so start two swaps into the hour.
    lo = np.clip(cuts[:-1] + 2, 0, len(csb) - 1)
    hi = np.clip(cuts[1:], 0, len(csb) - 1)
    bv = np.sqrt(np.maximum(csb[hi] - csb[lo], 0.0) * (np.pi / 2.0))
    return rv, bv


def ewma_shift1(values: np.ndarray, halflife: float) -> np.ndarray:
    """Signal at boundary t = EWMA of values[0..t-1] (NaN at t=0)."""
    return (pd.Series(values).shift(1)
            .ewm(halflife=halflife, min_periods=1).mean().to_numpy())


def log_safe(x: np.ndarray) -> np.ndarray:
    out = np.full_like(x, np.nan, dtype=float)
    m = x > 0
    out[m] = np.log(x[m])
    return out


def seasonal_signal(hs: np.ndarray, payoff: np.ndarray, kappa: float,
                    tune_end_epoch: int = AUG1_EPOCH) -> np.ndarray:
    """C3: per-hour dow×hod cell mean of payoff, cells estimated ONLY on hours
    with hs < tune_end_epoch, shrunk toward the tune-window global mean."""
    t = pd.to_datetime(hs, unit="s", utc=True)
    key = t.dayofweek.to_numpy() * 24 + t.hour.to_numpy()
    tune = hs < tune_end_epoch
    if not tune.any():
        raise ValueError("empty tune window")
    global_mean = float(payoff[tune].mean())
    cells = np.full(168, global_mean)
    for k in range(168):
        sel = tune & (key == k)
        n = int(sel.sum())
        if n:
            cells[k] = (n * float(payoff[sel].mean()) + kappa * global_mean) / (n + kappa)
    return cells[key]


def load_binance() -> tuple[np.ndarray, np.ndarray]:
    with gzip.open(BINANCE_CSV, "rt") as f:
        df = pd.read_csv(f)
    return df["open_time_s"].to_numpy(np.int64), df["close"].to_numpy(np.float64)


def binance_rv_signal(hs: np.ndarray, bt: np.ndarray, bclose: np.ndarray,
                      lookback_min: int) -> np.ndarray:
    """C4 at boundary t: sqrt(sum of squared 1m log-close returns) over the
    klines with open_time in [t - 60*lookback, t). The kline opening at t-60
    closes AT t, so the newest input is known exactly at the boundary. NaN
    unless the window holds the full `lookback_min` klines."""
    logc = np.log(bclose)
    d2 = np.concatenate([[0.0], np.diff(logc) ** 2])
    cs = np.concatenate([[0.0], np.cumsum(d2)])
    a = np.searchsorted(bt, hs - 60 * lookback_min, side="left")
    b = np.searchsorted(bt, hs, side="left")
    out = np.full(len(hs), np.nan)
    ok = (b - a) == lookback_min
    # d2[i] is the return between kline i-1 and i; both inside [a, b) iff i > a
    out[ok] = np.sqrt(cs[b[ok]] - cs[a[ok] + 1])
    return out


# --------------------------------------------------------------------------
def build_all(w: int, swaps: pd.DataFrame) -> dict[str, dict]:
    """Every candidate's signal family for width w, keyed by candidate then
    by parameter value. Each entry: (signal array over the hour grid, rule
    direction: +1 for enter-iff->=, -1 for enter-iff-<=)."""
    hours = load_hours(w)
    hs = hours["hour_epoch"].to_numpy(np.int64)
    payoff = hours["payoff_usd"].to_numpy(np.float64)
    rv, bv = hourly_rv_bv(hs, swaps)
    bt, bclose = load_binance()

    fam: dict[str, dict] = {"c1": {}, "c2": {}, "c3": {}, "c4": {}, "c5": {}}
    for lam in EWMA_HALFLIVES:
        fam["c1"][lam] = (ewma_shift1(payoff, lam), +1)
        fam["c2"][lam] = (ewma_shift1(log_safe(rv), lam), -1)
        fam["c5"][lam] = (ewma_shift1(log_safe(bv), lam), -1)
    for kappa in SEASONAL_KAPPAS:
        fam["c3"][kappa] = (seasonal_signal(hs, payoff, kappa), +1)
    for n in BINANCE_LOOKBACKS_MIN:
        fam["c4"][n] = (binance_rv_signal(hs, bt, bclose, n), -1)
    return fam
