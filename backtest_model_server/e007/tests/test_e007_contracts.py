#!/usr/bin/env python3
"""E007 blocking contracts (pre-registered in loop/experiments/E007).

    nix develop .#gate1 -c python backtest_model_server/e007/tests/test_e007_contracts.py

1. always_in through E007's evaluator == E003's committed lag1h_rh1h
   always_in, float-exact, w4 + w10, all three envelope points.
2. always_cash nets exactly $0 with zero streaks.
3. Accounting identity per simulated streak <= 1e-6 (asserted inside the
   evaluator on every streak; re-checked here over everything cached).
4. Causality: signals recomputed from truncated data equal the full-series
   values at sampled boundaries (C1/C2/C4/C5 strict; C3 is a tune-window
   calendar estimator — checked to be invariant to August data instead).
5. Tuning isolation: the tuning routine raises when fed held-out rows.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

E007 = Path(__file__).resolve().parent.parent
BMS = E007.parent
for p in (BMS / "gate1", BMS / "e003", BMS / "e006", E007):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import race                    # noqa: E402
import causal_signals as CS    # noqa: E402
import evaluate as EV          # noqa: E402
from run_candidates import tune_candidate  # noqa: E402

N_CHECKS = 0
FAILED = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global N_CHECKS
    N_CHECKS += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


e003_by_arm = {a["arm"]: a for a in json.loads(
    (BMS / "e003" / "out" / "lag1h_rh1h" / "results.json").read_text())["arms"]}
swaps = race.load_swaps("2026-05-01", "2026-08-28")
funding = race.load_funding()

# --- 1 + 2: always_in float-exact, always_cash zero -------------------------
print("contract 1+2: always_in reproduction, always_cash zero")
for w in (4, 10):
    hours = CS.load_hours(w)
    hs = hours["hour_epoch"].to_numpy(np.int64)
    cache = EV.StreakCache(w)
    r_in = EV.evaluate_mask(np.ones(len(hs), bool), hs, swaps, funding, cache)
    exp = e003_by_arm[f"always_in_w{w}"]["total"]
    for pt in ("optimistic", "central", "pessimistic"):
        got, want = EV.net_usd(r_in["total"], pt), exp[f"net_usd_{pt}"]
        check(f"w{w} always_in net_{pt} exact", got == want,
              f"got {got!r} want {want!r}")
    check(f"w{w} always_in n_recenters exact",
          r_in["total"]["n_recenters"] == exp["n_recenters"])
    check(f"w{w} always_in lp_fees exact",
          r_in["total"]["lp_fees_usd"] == exp["lp_fees_usd"])
    check(f"w{w} always_in is one streak", r_in["n_streaks"] == 1)
    r_cash = EV.evaluate_mask(np.zeros(len(hs), bool), hs, swaps, funding, cache)
    check(f"w{w} always_cash zero",
          EV.net_usd(r_cash["total"], "central") == 0.0
          and r_cash["n_streaks"] == 0)
    cache.save()

# --- 3: accounting identity over everything cached ---------------------------
print("contract 3: accounting identity over all cached streaks")
for w in (4, 10):
    path = E007 / "out" / f"cache_w{w}.json"
    if not path.exists():
        check(f"w{w} cache exists", False)
        continue
    entries = [e for e in json.loads(path.read_text()).values()
               if not e.get("empty")]
    worst = max((e["gap"] for e in entries), default=0.0)
    check(f"w{w} max gap <= 1e-6 over {len(entries)} cached streaks",
          worst <= 1e-6, f"{worst:.2e}")

# --- 4: causality by recomputation from truncated data -----------------------
print("contract 4: causality (truncated recomputation)")
hours4 = CS.load_hours(4)
hs4 = hours4["hour_epoch"].to_numpy(np.int64)
payoff4 = hours4["payoff_usd"].to_numpy(np.float64)
rv, bv = CS.hourly_rv_bv(hs4, swaps)
bt, bclose = CS.load_binance()
SAMPLE = [200, 1000, 2000, 2500, len(hs4) - 1]

for lam in (2, 24):
    full_c1 = CS.ewma_shift1(payoff4, lam)
    full_c2 = CS.ewma_shift1(CS.log_safe(rv), lam)
    full_c5 = CS.ewma_shift1(CS.log_safe(bv), lam)
    ok1 = ok2 = ok5 = True
    for t in SAMPLE:
        # truncated: only hours < t exist
        ok1 &= np.isclose(CS.ewma_shift1(payoff4[:t + 1], lam)[t], full_c1[t],
                          rtol=0, atol=0, equal_nan=True)
        ok2 &= np.isclose(CS.ewma_shift1(CS.log_safe(rv)[:t + 1], lam)[t],
                          full_c2[t], rtol=0, atol=0, equal_nan=True)
        ok5 &= np.isclose(CS.ewma_shift1(CS.log_safe(bv)[:t + 1], lam)[t],
                          full_c5[t], rtol=0, atol=0, equal_nan=True)
    check(f"C1 ewma lam={lam} causal (exact at truncation)", bool(ok1))
    check(f"C2 ewma lam={lam} causal", bool(ok2))
    check(f"C5 ewma lam={lam} causal", bool(ok5))

for n in (15, 60):
    full_c4 = CS.binance_rv_signal(hs4, bt, bclose, n)
    ok4 = True
    for t in SAMPLE:
        cut = np.searchsorted(bt, hs4[t], side="left")   # klines opening < t
        trunc = CS.binance_rv_signal(hs4[t:t + 1], bt[:cut], bclose[:cut], n)[0]
        ok4 &= (np.isnan(trunc) and np.isnan(full_c4[t])) or trunc == full_c4[t]
    check(f"C4 lookback={n}m causal (truncated kline set)", bool(ok4))

# C3: calendar estimator — signal must be invariant to any August data
s3_full = CS.seasonal_signal(hs4, payoff4, kappa=8)
payoff_scrambled = payoff4.copy()
aug = hs4 >= CS.AUG1_EPOCH
payoff_scrambled[aug] = 1e9
s3_scrambled = CS.seasonal_signal(hs4, payoff_scrambled, kappa=8)
check("C3 cells invariant to held-out August data",
      bool(np.array_equal(s3_full, s3_scrambled)))

# hourly RV matches a direct recompute under E006's boundary convention
# (the return connecting the previous hour's last swap into this hour's first
# swap belongs to this hour — signals.py's rv_swap does the same)
t = 1500
ts_all = swaps["timestamp"].to_numpy(np.int64)
lo = int(np.searchsorted(ts_all, hs4[t], side="right")) - 1
hi = int(np.searchsorted(ts_all, hs4[t] + 3600, side="right"))
lp = np.log(swaps["price"].to_numpy()[lo:hi])
check("hourly RV matches direct recompute (E006 boundary convention)",
      bool(np.isclose(np.sqrt((np.diff(lp) ** 2).sum()), rv[t],
                      rtol=1e-12, atol=1e-15)))

# --- 5: tuning isolation ------------------------------------------------------
print("contract 5: tuning refuses held-out rows")
try:
    tune_candidate("c2", {2: (CS.ewma_shift1(CS.log_safe(rv), 2), -1)},
                   hs4, 92.0, swaps, funding, EV.StreakCache(4))
    check("tune_candidate(full window incl. August) raises", False)
except AssertionError:
    check("tune_candidate(full window incl. August) raises", True)

print(f"\n{N_CHECKS} checks, {len(FAILED)} failed" + (f": {FAILED}" if FAILED else ""))
sys.exit(1 if FAILED else 0)
