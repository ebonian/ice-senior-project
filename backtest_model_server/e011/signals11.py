#!/usr/bin/env python3
"""E011 descriptive signals — do E006's findings transfer? (non-deciding)

    nix develop .#gate1 -c python backtest_model_server/e011/signals11.py

E006's set, reused by import (trailing_signals / auc / autocorr /
dist_stats from e006/signals.py), on the verdict arm's held set: trailing
RV and Kaufman ER at 12/24/48h on the USD close series (pool price × ETH
mark), previous-hour intra-hour RV, persistence ACFs — plus the same-hour
component AUCs (what the oracle actually selects on, with foresight) and a
split-sample dow×hod calendar (cells from May–Jul, AUC on August — E007's
selector shape, descriptive only).

Judges nothing; feeds a hypothetical E012.

Output: out/descriptive.json.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import common11 as C

E6S = C.E6S
WINDOWS = (12, 24, 48)
WARMUP = max(WINDOWS)


def main() -> int:
    stage2 = C.read_json(C.OUT / "stage2_results.json")
    best = stage2["best_arm_central"]
    hrs = pd.read_csv(C.OUT / f"stage1_hours_{best}.csv")
    held = hrs["held_central"].to_numpy(bool)
    hs = hrs["hour_epoch"].to_numpy(np.int64)
    n_hours = len(hs)

    closes = np.concatenate([
        (hrs["p0"] * hrs["u0"]).to_numpy(),
        [float(hrs["p1"].iloc[-1] * hrs["u1"].iloc[-1])]])
    sig = E6S.trailing_signals(closes)
    valid = np.zeros(n_hours, dtype=bool)
    valid[WARMUP:] = True

    signals_out = {}
    for name, s in sig.items():
        sh = s[:n_hours]
        m = valid & ~np.isnan(sh)
        signals_out[name] = {
            "auc_for_held": E6S.auc(sh[m], held[m]),
            "held": E6S.dist_stats(sh[m & held]),
            "skipped": E6S.dist_stats(sh[m & ~held]),
        }

    # Intra-hour realized vol from the swap stream (persistence + prev-1h).
    spec, swaps, funding, marks = C.load_all()
    ts = swaps["timestamp"].to_numpy(np.int64)
    logp = np.log(swaps["price"].to_numpy(np.float64))
    d2 = np.concatenate([[0.0], np.diff(logp) ** 2])
    cuts = np.searchsorted(ts, np.concatenate([hs, [hs[-1] + 3600]]),
                           side="right")
    csum = np.concatenate([[0.0], np.cumsum(d2)])
    rv_swap = np.sqrt(csum[cuts[1:]] - csum[cuts[:-1]])

    rv_prev = np.concatenate([[np.nan], rv_swap[:-1]])
    m = valid & ~np.isnan(rv_prev)
    signals_out["rv_prev_1h"] = {
        "auc_for_held": E6S.auc(rv_prev[m], held[m]),
        "held": E6S.dist_stats(rv_prev[m & held]),
        "skipped": E6S.dist_stats(rv_prev[m & ~held]),
    }

    # Same-hour (foresight) component AUCs — what the oracle selects on.
    same_hour = {}
    for col in ("payoff_usd", "gamma_pnl_usd", "fees_usd"):
        same_hour[col] = E6S.auc(hrs[col].to_numpy(), held)
    same_hour["rv_intra_hour"] = E6S.auc(rv_swap, held)

    # Split-sample dow×hod calendar: cell mean payoff May–Jul, AUC on Aug.
    t = pd.to_datetime(hs, unit="s", utc=True)
    dow, hod = t.dayofweek.to_numpy(), t.hour.to_numpy()
    aug = t >= pd.Timestamp("2026-08-01", tz="UTC")
    pay = hrs["payoff_usd"].to_numpy()
    cells = np.full((7, 24), np.nan)
    for d in range(7):
        for h in range(24):
            sel = (dow == d) & (hod == h) & ~aug
            if sel.any():
                cells[d, h] = pay[sel].mean()
    cal = cells[dow, hod]
    calendar = {
        "auc_full_window_in_sample": E6S.auc(cal, held),
        "auc_august_out_of_sample": E6S.auc(cal[aug], held[aug]),
        "cells_from": "2026-05-01..2026-07-31 mean payoff, dow x hod",
    }

    persistence = {"rv_intra_hour": E6S.autocorr(rv_swap)}
    for n in WINDOWS:
        persistence[f"er_{n}h"] = E6S.autocorr(sig[f"er_{n}h"][:n_hours])
    rv_rank = pd.Series(rv_swap).rank(pct=True).to_numpy()
    persistence["rv_intra_hour_rank"] = E6S.autocorr(rv_rank)

    runs = C.E6O.streaks_of(held)
    lengths = np.array([j - i + 1 for i, j in runs]) if runs else np.array([0])
    month_lab = t.strftime("%Y-%m")
    monthly = {lab: {"hours": int((month_lab == lab).sum()),
                     "held_frac": float(held[month_lab == lab].mean())}
               for lab in sorted(set(month_lab))}

    payload = {
        "experiment": "E011",
        "section": "descriptive (NOT part of the verdict)",
        "best_arm": best,
        "oracle_structure": {
            "held_hours": int(held.sum()), "total_hours": n_hours,
            "held_frac": float(held.mean()), "n_streaks": len(runs),
            "streak_hours": {"mean": float(lengths.mean()),
                             "p50": float(np.percentile(lengths, 50)),
                             "p90": float(np.percentile(lengths, 90)),
                             "max": int(lengths.max())},
            "monthly": monthly,
        },
        "same_hour_auc_foresight": same_hour,
        "signals_trailing_causal": signals_out,
        "calendar_dow_hod": calendar,
        "persistence_acf_lags_1_24": persistence,
        "notes": "AUC is P(signal at a held hour > signal at a skipped "
                 "hour); 0.5 = none. Trailing signals are causal; same-hour "
                 "AUCs use foresight and exist only to describe what the "
                 "oracle selects on. Warm-up 48h excluded.",
    }
    C.write_json(C.OUT / "descriptive.json", payload)
    for name, s in signals_out.items():
        print(f"{name:<10s} AUC {s['auc_for_held']:.3f}")
    print("same-hour:", {k: round(v, 3) for k, v in same_hour.items()})
    print("calendar:", {k: (round(v, 3) if isinstance(v, float) else v)
                        for k, v in calendar.items()})
    print(f"held {held.mean()*100:.1f}% in {len(runs)} streaks "
          f"(median {np.percentile(lengths, 50):.0f}h, max {lengths.max()}h)")
    print(f"wrote {C.OUT/'descriptive.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
