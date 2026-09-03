#!/usr/bin/env python3
"""E011 blocking contracts. Run before trusting any number in REPORT.md.

    nix develop .#gate1 -c python backtest_model_server/e011/tests/test_e011_contracts.py

What can silently invalidate this experiment, and the check that catches it:

  1. ENGINE-PATH DRIFT — a single streak spanning the whole window through
     the stage-2 path must reproduce E010's committed
     lag1h_rh1h_cap10000_gas-{opt,central,pess} rows float-consistently
     (<= 1e-9 rel / 1e-6 abs on every Bucket field and per-day number), at
     all three coupled gas points. This is the pre-registered baseline
     contract: always-in IS one unbroken streak.
  2. always_cash == $0.00 exactly at every envelope point.
  3. FUNDING INPUT IDENTITY — the fresh LINK fundingHistory fetch must
     reproduce E010's committed window input on the overlap (>= 99.9% of
     2,856 hours present, max |drate| <= 1e-12).
  4. Accounting identity on the reproduction runs (gap <= 1e-6).
  5. BOUND PROPERTY — stage-1 DP value >= its own always-in valuation and
     >= 0, per arm per point; and >= every constrained (coarseness) DP.
  6. Accounting identity per simulated stage-2 streak <= 1e-6.
  7. DETERMINISM — recomputing the wide arm's stage-1 table reproduces the
     checkpointed CSV byte-identically (via the same to_csv round-trip).

Checks whose artifacts do not exist yet print SKIP and do not fail; the
suite is re-run after every stage and must be all-PASS before REPORT.md.
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

E011 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(E011))

import common11 as C  # noqa: E402

REL, ABS = 1e-9, 1e-6
OUT = C.OUT
FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          f"{('  — ' + detail) if detail else ''}", flush=True)
    if not ok:
        FAILS.append(name)


def skip(name: str, why: str) -> None:
    print(f"  SKIP  {name}  — {why}", flush=True)


def close(a: float, b: float) -> bool:
    return abs(a - b) <= max(ABS, REL * max(abs(a), abs(b)))


# --- 1+4: E010 race-row reproduction at all three coupled gas points -------
print("[1/4] E010 race-row reproduction (always-in == one unbroken streak)")
spec, swaps, funding, marks = C.load_all()
ts = swaps["timestamp"].to_numpy(np.int64)
t_from, t_to = int(ts[0]), int(ts[-1]) + 1
for point in C.POINTS:
    committed = C.read_json(C.E010_RESULTS[point])
    by_label = {a["arm"]: a for a in committed["arms"]}
    for arm in C.arms():
        with C.chain_gas(point):
            r = C.simulate_streak(arm, t_from, t_to)
        want = by_label[arm["label"]]
        bad = []
        for f in C.BUCKET_FIELDS:
            got, exp = getattr(r.total, f), want["total"][f]
            if not close(got, exp):
                bad.append(f"{f}: {got!r} vs {exp!r}")
        for pn in C.POINTS:
            got = r.total.per_day(C.ENVELOPE_BY_NAME[pn])
            exp = want["total"][f"per_day_{pn}"]
            if not close(got, exp):
                bad.append(f"per_day_{pn}: {got!r} vs {exp!r}")
        check(f"repro/{point}/{arm['label']}", not bad, "; ".join(bad[:3]))
        check(f"identity-gap/{point}/{arm['label']}",
              r.checks["lp_value_abs_gap_usd"] <= 1e-6,
              f"gap {r.checks['lp_value_abs_gap_usd']:.2e}")

# --- 2: always_cash is exactly zero ----------------------------------------
print("[2] always_cash == $0.00")
cash = C.R5.always_cash(100.0, {"2026-05": 100.0})
ok = all(cash.total.net_usd(C.ENVELOPE_BY_NAME[pn]) == 0.0
         for pn in C.POINTS)
ok = ok and all(getattr(cash.total, f) == 0.0
                for f in C.BUCKET_FIELDS if f != "hours")
check("always-cash-zero", ok)

# --- 3: funding-recompute cross-check --------------------------------------
print("[3] LINK funding recompute cross-check (fresh long fetch vs committed)")
fresh_p = E011 / "data" / "hl_funding_link_hourly_long.csv"
committed_p = C.BMS / "e005" / "data" / "funding" / "hl_funding_link_hourly.csv"
if not fresh_p.exists():
    skip("funding-crosscheck", "fetch11.py has not run")
else:
    fresh = {}
    with open(fresh_p) as f:
        for row in csv.DictReader(f):
            fresh[int(row["time_ms"]) // 3_600_000] = float(
                row["funding_rate_hourly"])
    n = present = 0
    worst = 0.0
    with open(committed_p) as f:
        for row in csv.DictReader(f):
            n += 1
            k = int(row["time_ms"]) // 3_600_000
            if k in fresh:
                present += 1
                worst = max(worst, abs(
                    fresh[k] - float(row["funding_rate_hourly"])))
    check("funding-crosscheck-rows", n == 2856, f"committed rows {n}")
    check("funding-crosscheck-overlap", present / n >= 0.999,
          f"{present}/{n} present")
    check("funding-crosscheck-values", worst <= 1e-12,
          f"max |drate| {worst:.3e}")

# --- 5: bound property ------------------------------------------------------
print("[5] bound property (DP >= always-in valuation, >= cash, >= constrained)")
s1p = OUT / "stage1_results.json"
if not s1p.exists():
    skip("bound-property", "stage 1 has not run")
else:
    s1 = C.read_json(s1p)
    for label, arm in s1["arms"].items():
        for pn, pt in arm["points"].items():
            check(f"bound/{label}/{pn}/vs-alwaysin",
                  pt["value_usd"] >= pt["alwaysin_stage1_usd"] - ABS)
            check(f"bound/{label}/{pn}/vs-cash", pt["value_usd"] >= -ABS)
    cop = OUT / "coarse_results.json"
    if not cop.exists():
        skip("bound-vs-constrained", "coarse11 has not run")
    else:
        co = C.read_json(cop)
        for label, arm in co["arms"].items():
            free = s1["arms"][label]["points"]["central"]["value_usd"]
            for cname, cv in arm["constraints"].items():
                check(f"bound/{label}/central/vs-{cname}",
                      free >= cv["stage1_value_usd"] - ABS)

# --- 6: stage-2 accounting identity ----------------------------------------
print("[6] stage-2 accounting identity")
s2p = OUT / "stage2_results.json"
if not s2p.exists():
    skip("stage2-identity", "stage 2 has not run")
else:
    s2 = C.read_json(s2p)
    for label, arm in s2["arms"].items():
        check(f"stage2-gap/{label}",
              arm["max_lp_value_abs_gap_usd"] <= 1e-6,
              f"max gap {arm['max_lp_value_abs_gap_usd']:.2e}")

# --- 7: stage-1 determinism (wide arm recompute) ----------------------------
print("[7] stage-1 determinism (wide arm)")
csv_p = OUT / "stage1_hours_arm_8.3pct.csv"
if not csv_p.exists():
    skip("determinism", "stage 1 has not run")
else:
    import oracle11 as O
    hs = C.E6O.hour_grid(ts)
    arm = next(a for a in C.arms() if a["label"] == "arm_8.3pct")
    hours = O.hourly_payoffs(arm, spec, swaps, funding, marks, hs,
                             C.LP_CAPITAL)
    for pn in C.POINTS:
        enter, exit_ = O.switch_costs(hours, pn)
        _, held = C.E6O.dp_select(hours["payoff_usd"].to_numpy(),
                                  enter, exit_)
        hours[f"held_{pn}"] = held
    buf = io.StringIO()
    hours.to_csv(buf, index=False)
    check("determinism-wide-arm", buf.getvalue() == csv_p.read_text(),
          "recomputed to_csv bytes vs raw checkpoint bytes")

print()
if FAILS:
    print(f"{len(FAILS)} FAILURES:")
    for f in FAILS:
        print(f"  {f}")
    sys.exit(1)
print("all contracts PASS (skips noted above are pre-stage only)")
