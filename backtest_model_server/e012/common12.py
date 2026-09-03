"""E012 shared plumbing: E011's frozen surface + the gate-mask engine.

REUSED BY IMPORT (no copies — the evaluator that judges the gate is the one
that priced the ceiling):
    e011/common11.py   engine path (e010 registry/race10 → e005 R5), arms,
                       coupled gas patching, simulate_streak, net_usd
    e011/exact11.py    run_streaks — the stage-2 exact evaluator
    e011 committed out/stage1_hours_*.csv   hourly closes p0·u0 (arm-invariant)
    e010 committed parquets + funding       via common11.load_all()

WRITTEN HERE (E012-specific, no engine semantics):
    signal construction (trailing RV, swap-RV medians, EWMA-RV, HAR z-blend),
    the two-threshold / dwell gate-mask generator (M006 §4 common block),
    the guarded mask evaluator (tuning isolation is enforced HERE: any
    simulation request at or past 2026-08-01T00:00Z raises unless the
    caller passes the frozen-params token).

Pre-registration: loop/experiments/E012-vol-gate-capture.md.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

E012 = Path(__file__).resolve().parent
BMS = E012.parent
E011 = BMS / "e011"
OUT = E012 / "out"

if str(E011) not in sys.path:
    sys.path.insert(0, str(E011))

import common11 as C11  # noqa: E402  (sets up e010/e005/gate1 paths)
import exact11 as X11   # noqa: E402

TUNE_END_EPOCH = int(datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp())
ARM_LABELS = ("arm_0.1pct_0.2pct_0.5pct", "arm_8.3pct")   # pre-registered two
POINTS = C11.POINTS
TARGET_10PCT = C11.TARGET_10PCT                            # 2.7397.../day
BEST_STATIC_PER_DAY = None    # read from committed E010 rows by tables12

VERDICT_ARM_CSV = C11.OUT / "stage1_hours_arm_0.1pct_0.2pct_0.5pct.csv"


def arms12():
    return [a for a in C11.arms() if a["label"] in ARM_LABELS]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_parquets() -> list[str]:
    """sha256 of each committed month parquet vs its committed meta. Returns
    the list of verified months; raises on any mismatch."""
    d = C11.E010 / "data" / "swaps" / "m_link_weth_0p30"
    ok = []
    for meta_p in sorted(d.glob("2026-*.meta.json")):
        meta = json.loads(meta_p.read_text())
        pq = d / (meta_p.name.replace(".meta.json", ".parquet"))
        got = sha256(pq)
        if got != meta["sha256"]:
            raise RuntimeError(f"sha256 mismatch {pq.name}: {got} != "
                               f"{meta['sha256']}")
        ok.append(meta_p.name.split(".")[0])
    if len(ok) != 4:
        raise RuntimeError(f"expected 4 committed months, saw {ok}")
    return ok


# --- hour grid and close series (arm-invariant, from committed E011 CSVs) ---

_cache: dict = {}


def hours_and_closes():
    """(hs[n], closes[n+1]) — closes[t] = USD price at boundary t (p0·u0 of
    hour t; final = last hour's p1·u1). Committed E011 stage-1 CSV."""
    if "hs" not in _cache:
        df = pd.read_csv(VERDICT_ARM_CSV)
        hs = df["hour_epoch"].to_numpy(np.int64)
        closes = np.concatenate([
            (df["p0"] * df["u0"]).to_numpy(np.float64),
            [float(df["p1"].iloc[-1] * df["u1"].iloc[-1])]])
        _cache["hs"], _cache["closes"] = hs, closes
    return _cache["hs"], _cache["closes"]


def hourly_returns():
    _, closes = hours_and_closes()
    return np.diff(np.log(closes))     # r[t-1] = return over hour ending at t


def swap_rv():
    """rv_swap[h] = intra-hour realized vol of hour h from the swap stream
    (signals11.py's construction, unchanged). Causal at boundary h+1."""
    if "rv_swap" not in _cache:
        hs, _ = hours_and_closes()
        _, swaps, _, _ = C11.load_all()
        ts = swaps["timestamp"].to_numpy(np.int64)
        logp = np.log(swaps["price"].to_numpy(np.float64))
        d2 = np.concatenate([[0.0], np.diff(logp) ** 2])
        cuts = np.searchsorted(ts, np.concatenate([hs, [hs[-1] + 3600]]),
                               side="right")
        csum = np.concatenate([[0.0], np.cumsum(d2)])
        _cache["rv_swap"] = np.sqrt(csum[cuts[1:]] - csum[cuts[:-1]])
    return _cache["rv_swap"]


# --- signal constructors (value at boundary t uses data <= t only) ----------

def trailing_rv(n: int) -> np.ndarray:
    """RV_n at boundary t = std(r[t-n:t], ddof=1) — e006 trailing_signals'
    definition on the USD close series; NaN before the window fills.
    Length = n_hours (indexed by decision boundary)."""
    key = f"rv_{n}"
    if key not in _cache:
        hs, _ = hours_and_closes()
        r = hourly_returns()
        nb = len(hs)
        out = np.full(nb, np.nan)
        for t in range(n, nb):
            out[t] = np.std(r[t - n: t], ddof=1)
        _cache[key] = out
    return _cache[key]


def swap_rv_median(m: int) -> np.ndarray:
    """Median of the last m completed hours' intra-hour swap RV, at
    boundary t: median(rv_swap[t-m:t]); NaN for t < m."""
    key = f"swapmed_{m}"
    if key not in _cache:
        rvs = swap_rv()
        nb = len(rvs)
        out = np.full(nb, np.nan)
        for t in range(m, nb):
            out[t] = np.median(rvs[t - m: t])
        _cache[key] = out
    return _cache[key]


EWMA_SEED_H = 48


def ewma_rv(lam: float) -> np.ndarray:
    """EWMA vol at boundary t: sigma2_t = lam*sigma2_{t-1} + (1-lam)*r_{t-1}^2,
    seeded at t=48 with the mean of the first 48 squared returns; NaN
    before. Returns sqrt(sigma2)."""
    key = f"ewma_{lam}"
    if key not in _cache:
        hs, _ = hours_and_closes()
        r = hourly_returns()
        nb = len(hs)
        out = np.full(nb, np.nan)
        s2 = float(np.mean(r[:EWMA_SEED_H] ** 2))
        out[EWMA_SEED_H] = np.sqrt(s2)
        for t in range(EWMA_SEED_H + 1, nb):
            s2 = lam * s2 + (1.0 - lam) * float(r[t - 1] ** 2)
            out[t] = np.sqrt(s2)
        _cache[key] = out
    return _cache[key]


HAR_WINDOWS = (24, 72, 168)


def har_blend(zstats: dict | None = None):
    """Equal-weight mean of z-scored RV_24/72/168 (Corsi's cascade, no
    fitted coefficients). z mean/sd come from the TUNE window's valid
    hours; pass them in (frozen) or None to compute-and-return them.
    Returns (signal, zstats)."""
    hs, _ = hours_and_closes()
    comps = {n: trailing_rv(n) for n in HAR_WINDOWS}
    if zstats is None:
        tune = hs < TUNE_END_EPOCH
        zstats = {}
        for n, s in comps.items():
            m = tune & ~np.isnan(s)
            zstats[str(n)] = {"mean": float(s[m].mean()),
                              "sd": float(s[m].std(ddof=1))}
    z = [(comps[n] - zstats[str(n)]["mean"]) / zstats[str(n)]["sd"]
         for n in HAR_WINDOWS]
    return np.nanmean(np.stack(z), axis=0) * np.where(
        np.any(np.isnan(np.stack(z)), axis=0), np.nan, 1.0), zstats


def tune_quantile(sig: np.ndarray, q: float) -> float:
    """Quantile of the signal over the TUNE window's valid hours — the
    threshold-freezing rule. Never sees August."""
    hs, _ = hours_and_closes()
    m = (hs < TUNE_END_EPOCH) & ~np.isnan(sig)
    return float(np.quantile(sig[m], q))


# --- the gate-mask engine (M006 §4 common block) ----------------------------

def gate_mask_hysteresis(sig: np.ndarray, hs: np.ndarray, grain_h: int,
                         thr_in: float, thr_out: float) -> np.ndarray:
    """Two-threshold skip gate: state changes only at UTC boundaries
    divisible by grain_h; IN→OUT when sig >= thr_out, OUT→IN when
    sig <= thr_in; NaN (warm-up) holds state; initial state IN."""
    n = len(hs)
    period = grain_h * 3600
    mask = np.zeros(n, dtype=bool)
    state = True
    for t in range(n):
        s = sig[t]
        if hs[t] % period == 0 and not np.isnan(s):
            if state and s >= thr_out:
                state = False
            elif (not state) and s <= thr_in:
                state = True
        mask[t] = state
    return mask


def gate_mask_dwell(sig: np.ndarray, hs: np.ndarray, grain_h: int,
                    thr: float, dwell_h: int) -> np.ndarray:
    """Single-threshold gate with minimum dwell: skip while sig >= thr,
    hold while sig < thr, but after any state change no change is allowed
    for dwell_h hours. Initial state IN (no dwell clock running)."""
    n = len(hs)
    period = grain_h * 3600
    mask = np.zeros(n, dtype=bool)
    state = True
    last_change = None
    for t in range(n):
        s = sig[t]
        if (hs[t] % period == 0 and not np.isnan(s)
                and (last_change is None
                     or hs[t] - last_change >= dwell_h * 3600)):
            want = bool(s < thr)
            if want != state:
                state = want
                last_change = hs[t]
        mask[t] = state
    return mask


# --- the guarded exact evaluator -------------------------------------------

class AugustIsolationError(RuntimeError):
    pass


def eval_mask(arm: dict, mask: np.ndarray, hs: np.ndarray,
              points=("central",), t_max: int | None = None,
              unlock_heldout: bool = False) -> dict:
    """Evaluate a held mask stage-2 exact (exact11.run_streaks), per coupled
    point. TUNING ISOLATION: unless unlock_heldout, any simulated hour at or
    past TUNE_END_EPOCH raises. t_max truncates the mask (tune slice); a
    run reaching t_max's boundary books its exit there (run_streaks always
    charges the exit at the slice end)."""
    m = mask.copy()
    if t_max is not None:
        m &= hs < t_max
    runs = C11.E6O.streaks_of(m)
    for (i, j) in runs:
        if not unlock_heldout and int(hs[j]) + 3600 > TUNE_END_EPOCH:
            raise AugustIsolationError(
                f"streak ending {int(hs[j]) + 3600} crosses the tune "
                f"boundary {TUNE_END_EPOCH}")
    out = {"n_streaks": len(runs),
           "held_hours_mask": int(m.sum()),
           "points": {}}
    for pn in points:
        total, months, rows, max_gap = X11.run_streaks(arm, runs, hs, pn)
        pt = C11.ENVELOPE_BY_NAME[pn]
        net = C11.net_usd(total, pt) if total else 0.0
        rec = {"net_usd": net,
               "n_streaks_simulated": len(rows),
               "held_hours_simulated": float(total.get("hours", 0.0)),
               "n_recenters": float(total.get("n_recenters", 0)),
               "max_lp_value_abs_gap_usd": max_gap,
               "total": total,
               "months_net_usd": {k: (C11.net_usd(v, pt) if v else 0.0)
                                  for k, v in sorted(months.items())}}
        if pn == "central":
            rec["streak_rows"] = rows
        out["points"][pn] = rec
    return out


def mask_key(arm_label: str, mask: np.ndarray, t_max, points) -> str:
    h = hashlib.sha1(mask.tobytes()).hexdigest()[:16]
    return f"{arm_label}|{h}|{t_max}|{','.join(points)}"


def read_json(p: Path) -> dict:
    return json.loads(p.read_text())


def write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, sort_keys=False, default=float))
