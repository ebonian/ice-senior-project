#!/usr/bin/env python3
"""Contract tests for E006. BLOCKING — run before trusting any number in
REPORT.md.

    nix develop .#gate1 -c python backtest_model_server/e006/tests/test_e006_contracts.py

Four things can silently invalidate this experiment, and each gets a test:

  1. Frozen inputs. The cost model must be gate1's `gate1-2026-08-29` and the
     envelope E003's `e003-2026-08-29`, resolved from the frozen directories.
  2. The exact-simulation machinery. With switch costs at infinity the oracle
     never exits, so its one streak spans the whole window — and that streak,
     pushed through stage 2's simulator, must reproduce E003's committed
     `always_in` lag1h_rh1h results EXACTLY (it is the same `run_arm` on the
     same bytes). Any drift here poisons every stage-2 number.
  3. Domination. The DP's feasible set contains `always_in` (one unbroken
     streak) and `always_cash` (the empty set); the optimum must weakly beat
     both — including E003's exact always-in number, which stage-1's
     over-crediting valuation must not fall below.
  4. The accounting identity, per simulated streak, at <= 1e-6.

Tests 3 and 4 read out/stage1_results.json and out/stage2_results.json —
run oracle.py and exact.py first (run_all.sh orders this correctly).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

E006 = Path(__file__).resolve().parents[1]
BMS = E006.parent
for p in (BMS / "gate1", BMS / "e003", E006):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from engine import cost_model as CM   # noqa: E402
import envelope as ENV                 # noqa: E402
import race                            # noqa: E402
import exact                           # noqa: E402
import oracle                          # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  — ' + detail) if detail else ''}")
    if not ok:
        FAILS.append(name)


# --- 1. frozen inputs -------------------------------------------------------
print("frozen inputs")
check("cost model version", CM.COST_MODEL_VERSION == "gate1-2026-08-29",
      CM.COST_MODEL_VERSION)
check("cost model path", "gate1/engine/cost_model.py" in CM.__file__.replace("\\", "/"),
      CM.__file__)
check("envelope version", ENV.E003_ENVELOPE_VERSION == "e003-2026-08-29",
      ENV.E003_ENVELOPE_VERSION)
check("envelope path", "/e003/" in ENV.__file__.replace("\\", "/"), ENV.__file__)
pts = {p.name: p for p in ENV.ENVELOPE}
check("envelope points match e003",
      (pts["optimistic"].maker_share_notional, pts["optimistic"].slippage_bps,
       pts["optimistic"].chase_bps) == (0.95, 0.4, 0.0)
      and (pts["central"].maker_share_notional, pts["central"].slippage_bps,
           pts["central"].chase_bps) == (0.6463, 0.9, 0.0)
      and (pts["pessimistic"].maker_share_notional, pts["pessimistic"].slippage_bps,
           pts["pessimistic"].chase_bps) == (0.0, 2.0, 2.0))
check("E006 arms are E003 arms", all(w in ENV.WIDTH_ARMS for w in oracle.ARMS),
      str(oracle.ARMS))
check("arm widths are the pre-registered ±0.2/0.5/2.0/8.3%",
      [round(ENV.width_pct(w) * 100, 1) for w in oracle.ARMS] == [0.2, 0.5, 2.0, 8.3])

# --- 2. switch-cost→∞ oracle == E003 always_in (exact) ----------------------
print("switch-cost→∞ reproduces E003 lag1h_rh1h (exact)")
e003_results = json.loads(
    (BMS / "e003" / "out" / "lag1h_rh1h" / "results.json").read_text())
e003_by_arm = {a["arm"]: a for a in e003_results["arms"]}
swaps = race.load_swaps("2026-05-01", "2026-08-28")
funding = race.load_funding()
ts = swaps["timestamp"].to_numpy(np.int64)

E003_NET = {}
for w in oracle.ARMS:
    r = exact.simulate_streak(w, swaps, funding, int(ts[0]), int(ts[-1]) + 1)
    exp = e003_by_arm[f"always_in_w{w}"]["total"]
    for pt in ENV.ENVELOPE:
        got, want = r.total.net_usd(pt), exp[f"net_usd_{pt.name}"]
        check(f"W{w} net_usd_{pt.name} exact", got == want,
              f"got {got!r} want {want!r}")
        E003_NET[(w, pt.name)] = want
    check(f"W{w} n_recenters exact",
          r.total.n_recenters == exp["n_recenters"],
          f"got {r.total.n_recenters} want {exp['n_recenters']}")
    check(f"W{w} lp_fees exact", r.total.lp_fees_usd == exp["lp_fees_usd"],
          f"got {r.total.lp_fees_usd!r} want {exp['lp_fees_usd']!r}")

# --- 3. domination ----------------------------------------------------------
print("oracle dominates always_in and always_cash")
s1_path = E006 / "out" / "stage1_results.json"
if not s1_path.exists():
    check("stage1_results.json exists (run oracle.py first)", False)
else:
    s1 = json.loads(s1_path.read_text())
    for key, arm in s1["arms"].items():
        w = arm["width"]
        for pt_name, pt in arm["points"].items():
            check(f"{key} {pt_name}: UB >= always_cash (0)", pt["value_usd"] >= 0.0,
                  f"{pt['value_usd']:.3f}")
            check(f"{key} {pt_name}: UB >= stage-1 always-in path",
                  pt["value_usd"] >= pt["alwaysin_stage1_usd"] - 1e-9,
                  f"{pt['value_usd']:.3f} vs {pt['alwaysin_stage1_usd']:.3f}")
            check(f"{key} {pt_name}: UB >= E003 exact always_in",
                  pt["value_usd"] >= E003_NET[(w, pt_name)],
                  f"{pt['value_usd']:.3f} vs {E003_NET[(w, pt_name)]:.3f}")

# --- 4. accounting identity on stage-2 runs ---------------------------------
print("stage-2 accounting identity")
s2_path = E006 / "out" / "stage2_results.json"
if not s2_path.exists():
    check("stage2_results.json exists (run exact.py first)", False)
else:
    s2 = json.loads(s2_path.read_text())
    for key, arm in s2["arms"].items():
        check(f"{key} max |direct - decomposed| <= 1e-6",
              arm["max_lp_value_abs_gap_usd"] <= 1e-6,
              f"{arm['max_lp_value_abs_gap_usd']:.2e}")
        check(f"{key} every selected streak simulated",
              arm["n_streaks_simulated"] == arm["n_streaks_selected"],
              f"{arm['n_streaks_simulated']}/{arm['n_streaks_selected']}")

print()
if FAILS:
    print(f"{len(FAILS)} FAILURES: {FAILS}")
    raise SystemExit(1)
print("all contracts hold")
