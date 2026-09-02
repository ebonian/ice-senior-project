#!/usr/bin/env python3
"""E006 descriptive section — could a CAUSAL signal have known?

    nix develop .#gate1 -c python backtest_model_server/e006/signals.py

NOT part of the verdict (pre-registered as descriptive; it feeds E007's design
if E006 supports). For the best arm's central-envelope oracle, compare held vs
skipped hours on TRAILING signals computed from hourly closes strictly at or
before each hour's start — no lookahead:

  realized vol RV_n   std of the last n hourly log returns, n in {12, 24, 48}
  Kaufman ER_n        |P_t - P_{t-n}| / sum |P_i - P_{i-1}|, same n

Reports per-signal distributions (held vs skipped), AUC for predicting oracle
membership, persistence (autocorrelation at lags 1-24h) of intra-hour realized
vol (from the swap stream) and of each ER series, and the oracle's structure:
held fraction, streak count/length distribution, monthly breakdown.

Output: out/descriptive.json (tables.py renders it).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

E006 = Path(__file__).resolve().parent
BMS = E006.parent
for p in (BMS / "gate1", BMS / "e003", E006):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import race     # noqa: E402
import oracle   # noqa: E402

WINDOWS = (12, 24, 48)
WARMUP = max(WINDOWS)   # signals undefined before this many hours


def trailing_signals(closes: np.ndarray) -> dict[str, np.ndarray]:
    """Signal value at boundary t (index into `closes`), causal: uses closes
    [t-n .. t] only. closes[b] is the price AT boundary b; the signal at t is
    what a filter deciding about hour [t, t+1h) could have seen."""
    r = np.diff(np.log(closes))          # r[b-1] = return over hour ending at b
    n_b = len(closes)
    out: dict[str, np.ndarray] = {}
    for n in WINDOWS:
        rv = np.full(n_b, np.nan)
        er = np.full(n_b, np.nan)
        absmove = np.abs(np.diff(closes))
        cs = np.concatenate([[0.0], np.cumsum(absmove)])
        for t in range(n, n_b):
            rv[t] = np.std(r[t - n: t], ddof=1)
            denom = cs[t] - cs[t - n]
            er[t] = abs(closes[t] - closes[t - n]) / denom if denom > 0 else np.nan
        out[f"rv_{n}h"] = rv
        out[f"er_{n}h"] = er
    return out


def auc(x: np.ndarray, y: np.ndarray) -> float:
    """Rank-based AUC of score x for label y (ties midranked)."""
    m = ~np.isnan(x)
    x, y = x[m], y[m]
    n1, n0 = int(y.sum()), int((~y).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    order = pd.Series(x).rank(method="average").to_numpy()
    return float((order[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def autocorr(x: np.ndarray, max_lag: int = 24) -> list[float]:
    x = x[~np.isnan(x)]
    x = x - x.mean()
    v = float((x * x).mean())
    return [float((x[k:] * x[:-k]).mean() / v) for k in range(1, max_lag + 1)]


def dist_stats(x: np.ndarray) -> dict:
    x = x[~np.isnan(x)]
    if len(x) == 0:
        nan = float("nan")
        return {"n": 0, "mean": nan, "p25": nan, "p50": nan, "p75": nan}
    q = np.percentile(x, [25, 50, 75])
    return {"n": int(len(x)), "mean": float(x.mean()),
            "p25": float(q[0]), "p50": float(q[1]), "p75": float(q[2])}


def main() -> int:
    out_dir = E006 / "out"
    stage2 = json.loads((out_dir / "stage2_results.json").read_text())
    best_key = stage2["best_arm_central"]
    w = stage2["arms"][best_key]["width"]

    hours = pd.read_csv(out_dir / f"stage1_hours_w{w}.csv")
    held = hours["held_central"].to_numpy(bool)
    hs = hours["hour_epoch"].to_numpy(np.int64)
    n_hours = len(hs)
    # closes[b] = price at boundary b, b = 0..N (p0 of each hour + final p1)
    closes = np.concatenate([hours["p0"].to_numpy(), [hours["p1"].iloc[-1]]])

    sig = trailing_signals(closes)
    valid = np.zeros(n_hours, dtype=bool)
    valid[WARMUP:] = True

    signals_out = {}
    for name, s in sig.items():
        sh = s[:n_hours]     # signal at each hour's START boundary
        m = valid & ~np.isnan(sh)
        signals_out[name] = {
            "auc_for_held": auc(sh[m], held[m]),
            "held": dist_stats(sh[m & held]),
            "skipped": dist_stats(sh[m & ~held]),
        }

    # intra-hour realized vol from the swap stream, for persistence
    swaps = race.load_swaps(stage2["window"]["start"], stage2["window"]["end"])
    ts = swaps["timestamp"].to_numpy(np.int64)
    logp = np.log(swaps["price"].to_numpy(np.float64))
    d2 = np.concatenate([[0.0], np.diff(logp) ** 2])
    cuts = np.searchsorted(ts, np.concatenate([hs, [hs[-1] + 3600]]), side="right")
    csum = np.concatenate([[0.0], np.cumsum(d2)])
    rv_swap = np.sqrt(csum[cuts[1:]] - csum[cuts[:-1]])

    persistence = {"rv_intra_hour": autocorr(rv_swap)}
    for n in WINDOWS:
        persistence[f"er_{n}h"] = autocorr(sig[f"er_{n}h"][:n_hours])
    # AUC of intra-hour RV's own PREVIOUS hour as a causal signal, for reference
    rv_prev = np.concatenate([[np.nan], rv_swap[:-1]])
    m = valid & ~np.isnan(rv_prev)
    signals_out["rv_prev_1h"] = {
        "auc_for_held": auc(rv_prev[m], held[m]),
        "held": dist_stats(rv_prev[m & held]),
        "skipped": dist_stats(rv_prev[m & ~held]),
    }

    runs = oracle.streaks_of(held)
    lengths = np.array([j - i + 1 for i, j in runs]) if runs else np.array([0])
    month_lab = pd.to_datetime(hs, unit="s", utc=True).strftime("%Y-%m")
    monthly = {}
    for lab in sorted(set(month_lab)):
        sel = month_lab == lab
        monthly[lab] = {"hours": int(sel.sum()), "held": int(held[sel].sum()),
                        "held_frac": float(held[sel].mean())}

    payload = {
        "experiment": "E006", "section": "descriptive (NOT part of the verdict)",
        "best_arm": best_key, "width": w,
        "oracle_structure": {
            "held_hours": int(held.sum()), "total_hours": n_hours,
            "held_frac": float(held.mean()),
            "n_streaks": len(runs),
            "streak_hours": {"mean": float(lengths.mean()),
                             "p50": float(np.percentile(lengths, 50)),
                             "p90": float(np.percentile(lengths, 90)),
                             "max": int(lengths.max())},
            "monthly": monthly,
            "stage2_over_stage1_central":
                stage2["arms"][best_key]["stage2_over_stage1_central"],
        },
        "signals": signals_out,
        "persistence_acf_lags_1_24": persistence,
        "notes": "AUC is P(signal at a held hour > signal at a skipped hour); "
                 "0.5 = no separation. Signals are trailing-only (causal). "
                 "Warm-up: first 48 hours excluded.",
    }
    (out_dir / "descriptive.json").write_text(json.dumps(payload, indent=2))
    for name, s in signals_out.items():
        print(f"{name:<10s} AUC {s['auc_for_held']:.3f}  "
              f"held p50 {s['held']['p50']:.4g}  skipped p50 {s['skipped']['p50']:.4g}")
    print(f"held {held.mean()*100:.1f}% in {len(runs)} streaks "
          f"(median {np.percentile(lengths, 50):.0f}h, max {lengths.max()}h)")
    print(f"wrote {out_dir/'descriptive.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
