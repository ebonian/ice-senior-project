#!/usr/bin/env python3
"""E010 Parts A and B: the mechanical restatement and the Arbitrum re-bind.

    nix develop .#gate1 -c python backtest_model_server/e010/parts_ab.py

PART A — restate E003 / E006 / E007 / E008 headline numbers and verdict signs
at $10k and $50k. The frozen stack decomposes per window as

    net = proportional + fixed_gas,   fixed_gas = onchain - swapped_ntl x 5.155bps

(exact under cost_model.onchain_cost: everything except per-tx gas and the
failed-mint charge is bps on notional). The pre-registered restatement is the
LINEAR one: net(s) = s x (net + gasF)/1 - gasF with s the LP-notional ratio.
Where an artifact has no Bucket (E007/E008 finals), fixed gas is approximated
as n_streaks x (6 tx + 0.19 failed) x $0.0101 — stated, not hidden.
CAVEAT (measured in the contract tests, §8): the engine's fee credit is
share-aware and concave in capital, so linear restatement OVERSTATES fee
income at larger capital — negative verdicts restate a fortiori; positive
ceilings (E006) are upper bounds twice over.

PART B — the $10k share re-bind for every E005-screened pool x arm:
  (i) pre-registered linear scaling: implied_share x 7147.887/1015 = x7.0423;
  (ii) measured: the two watchlist pools re-raced at $10k on their own
       committed parquets (race10 --slug e005:<slug>), shares recomputed by
       the engine's own concave fee credit.

Writes out/parts_ab.json and prints the tables.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

E010 = Path(__file__).resolve().parent
BMS = E010.parent
sys.path.append(str(E010))
for p in (str(BMS / "gate1"), str(BMS / "e005")):
    if p not in sys.path:
        sys.path.insert(0, p)
import registry as R  # noqa: E402

SWAP_BPS = 5.155e-4          # POOL_FEE_BPS + EXTRA_SWAP_SLIPPAGE_BPS, / 1e4
GAS = 0.0101
S10 = R.lp_notional(10_000.0) / 1015.0     # 7.0423...
S50 = R.lp_notional(50_000.0) / 1015.0


def linear_restate(pd_central: float, fixed_pd: float) -> dict:
    prop = pd_central + fixed_pd           # fixed_pd is a positive cost/day
    return {"per_day_1420": pd_central,
            "per_day_10k_linear": prop * S10 - fixed_pd,
            "per_day_50k_linear": prop * S50 - fixed_pd,
            "fixed_gas_per_day": fixed_pd}


def part_a() -> dict:
    out = {}

    # E003 — always-in width race, per matching arm
    e3 = json.loads((BMS / "e003" / "out" / "lag1h_rh1h" / "results.json").read_text())
    rows = {}
    for a in e3["arms"]:
        if not a.get("width"):
            continue
        t = a["total"]
        days = t["hours"] / 24.0
        fixed_pd = (t["onchain_cost_usd"] - t["swapped_notional_usd"] * SWAP_BPS) / days
        rows[a["arm"]] = {**linear_restate(t["per_day_central"], fixed_pd),
                          "recenters": t["n_recenters"]}
    best = max(rows.values(), key=lambda r: r["per_day_1420"])
    out["E003"] = {"verdict_1420": "REFUTED (no arm >= $0 even optimistic)",
                   "arms": rows,
                   "sign_flip_at_10k": any(r["per_day_10k_linear"] > 0
                                           for r in rows.values()),
                   "best_arm_10k_linear": best["per_day_10k_linear"]}

    # E006 — perfect-foresight oracle ceiling (stage 2)
    e6 = json.loads((BMS / "e006" / "out" / "stage2_results.json").read_text())
    rows = {}
    for w, a in e6["arms"].items():
        t = a["total"]
        days = e6["window"]["days"]
        fixed_pd = (t["onchain_cost_usd"] - t["swapped_notional_usd"] * SWAP_BPS) / days
        pd_c = a["points"]["central"]["per_day_usd"]
        rows[w] = linear_restate(pd_c, fixed_pd)
    out["E006"] = {"verdict_1420": "SUPPORTED (ceiling +$6.06/day at w4)",
                   "arms": rows,
                   "sign_flip_at_10k": any(r["per_day_10k_linear"] < 0
                                           for r in rows.values()),
                   "note": "ceiling scales ~linearly UP; share-aware fee "
                           "concavity makes the linear number an upper bound "
                           "(w4 implied share ~0.7% at $1.42k -> ~5% at $10k)"}

    # E007 / E008 — best candidates; finals carry no Bucket, so fixed gas is
    # the stated n_streaks approximation.
    def streak_restate(f: Path) -> dict:
        d = json.loads(f.read_text())
        days = d["full_window"]["days"]
        fixed_pd = d["n_streaks"] * (6 + 0.19) * GAS / days
        r = linear_restate(d["full_window"]["per_day_usd"]["central"], fixed_pd)
        r["august_per_day_1420"] = d["heldout_august"]["per_day_usd"]
        r["august_per_day_10k_linear"] = (
            (d["heldout_august"]["per_day_usd"]
             + fixed_pd) * S10 - fixed_pd)   # same fixed rate assumed in Aug
        r["n_streaks"] = d["n_streaks"]
        return r

    e7 = {}
    for f in sorted((BMS / "e007" / "out").glob("final_c*_w*.json")):
        e7[f.stem] = streak_restate(f)
    best7 = max(e7.values(), key=lambda r: r["per_day_1420"])
    out["E007"] = {"verdict_1420": "REFUTED (all 6 candidates negative, both arms)",
                   "candidates": e7,
                   "sign_flip_at_10k": any(r["per_day_10k_linear"] > 0
                                           for r in e7.values()),
                   "best_10k_linear": best7["per_day_10k_linear"]}

    e8 = {}
    for f in sorted((BMS / "e008" / "out").glob("final_s*_w*.json")):
        e8[f.stem] = streak_restate(f)
    best8 = max(e8.values(), key=lambda r: r["per_day_1420"])
    out["E008"] = {"verdict_1420": "REFUTED (all 6 mechanisms negative, both arms)",
                   "candidates": e8,
                   "sign_flip_at_10k": any(r["per_day_10k_linear"] > 0
                                           for r in e8.values()),
                   "best_10k_linear": best8["per_day_10k_linear"],
                   "august_still_negative_at_10k": all(
                       r["august_per_day_10k_linear"] < 0 for r in e8.values())}
    return out


def part_b() -> dict:
    d5 = json.loads((BMS / "e005" / "out" / "decision.json").read_text())
    rows = []
    for r in d5["arm_rows"]:
        if r["arm"] == "always_cash":
            continue
        lin10 = r["implied_pool_share"] * S10
        rows.append({"slug": r["slug"], "arm": r["arm"],
                     "share_1420": r["implied_pool_share"],
                     "share_10k_linear": lin10,
                     "gate_d_1420": r["implied_pool_share"] <= 0.01,
                     "gate_d_10k_linear": lin10 <= 0.01})
    lin = {"rows": rows,
           "survivors_10k": [f"{r['slug']}/{r['arm']}" for r in rows
                             if r["gate_d_10k_linear"]],
           "deaths_10k": [f"{r['slug']}/{r['arm']}" for r in rows
                          if r["gate_d_1420"] and not r["gate_d_10k_linear"]]}

    measured = {}
    for slug in ("wsteth_weth_0p01", "link_weth_0p05"):
        f = E010 / "out" / slug / "lag1h_rh1h_cap10000_gas-central" / "results.json"
        if not f.exists():
            continue
        rr = json.loads(f.read_text())
        tier = rr["pool"]["fee"] / 1e6
        shr = rr["pool"]["lp_fee_share"]
        arms = {}
        for a in rr["arms"]:
            if a["arm"] == "always_cash":
                continue
            t = a["total"]
            vir = t["volume_in_range_usd"]
            days = t["hours"] / 24.0
            arms[a["arm"]] = {
                "share_10k_measured": (t["lp_fees_usd"] / (vir * tier * shr)
                                       if vir else 0.0),
                "net_central_per_day_10k": t["per_day_central"],
                "funding_per_day_10k": t["funding_usd"] / days,
                "gate_d_10k_measured": (t["lp_fees_usd"] / (vir * tier * shr)
                                        if vir else 0.0) <= 0.01}
        measured[slug] = arms
    return {"linear": lin, "measured_reraces": measured,
            "lp_notional_ratio": S10}


def main() -> int:
    out = {"part_a": part_a(), "part_b": part_b(),
           "lp_notional": {"1420": 1015.0, "10k": R.LP_NOTIONAL_10K,
                           "50k": R.lp_notional(50000.0)}}
    (E010 / "out" / "parts_ab.json").write_text(json.dumps(out, indent=2))

    a = out["part_a"]
    print("== PART A: verdict signs at $10k (linear restatement) ==")
    for exp in ("E003", "E006", "E007", "E008"):
        flip = a[exp]["sign_flip_at_10k"]
        print(f"  {exp}: {a[exp]['verdict_1420']}")
        print(f"        sign flip at $10k: {'YES — FINDING' if flip else 'no'}")
    print(f"  E003 best arm: {a['E003']['arms']['always_in_w160']['per_day_1420']:+.3f} "
          f"-> {a['E003']['arms']['always_in_w160']['per_day_10k_linear']:+.3f} $/d")
    print(f"  E006 w4 ceiling: +6.058 -> "
          f"{a['E006']['arms']['w4']['per_day_10k_linear']:+.3f} $/d (upper bound)")
    print(f"  E007 best: {a['E007']['best_10k_linear']:+.4f} $/d at 10k")
    print(f"  E008 best: {a['E008']['best_10k_linear']:+.4f} $/d at 10k; "
          f"August all-negative: {a['E008']['august_still_negative_at_10k']}")
    b = out["part_b"]
    print("== PART B: share gate at $10k ==")
    print(f"  linear x{b['lp_notional_ratio']:.4f}: "
          f"{len(b['linear']['deaths_10k'])} arms die that passed at $1,420: "
          f"{b['linear']['deaths_10k']}")
    for slug, arms in b["measured_reraces"].items():
        for arm, v in arms.items():
            print(f"  measured {slug}/{arm}: share {v['share_10k_measured']*100:.3f}% "
                  f"gate_d={'PASS' if v['gate_d_10k_measured'] else 'FAIL'} "
                  f"net {v['net_central_per_day_10k']:+.3f}/d "
                  f"funding {v['funding_per_day_10k']:+.3f}/d")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
