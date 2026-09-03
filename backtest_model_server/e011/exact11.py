#!/usr/bin/env python3
"""E011 stage 2 — exact simulation of the DP-selected policy, coupled points.

    nix develop .#gate1 -c python backtest_model_server/e011/exact11.py

The CENTRAL coupled point's DP selection is the policy (E006's rule: one
policy, priced at every point — no point may change behaviour). Each streak
is re-simulated exactly through e005's `run_arm` (fresh mint, lag1h_rh1h
loop inside, burn + flatten at exit; cash outside). Because mainnet gas is
booked on-chain at simulation time, the coupling re-runs the SAME streaks
under each gas point and prices each run at its same-named HPL point —
behaviour (breach detection, hour grid, hedging) is gas-independent in the
engine, so the streaks and paths are identical; only the booked gas and the
HPL pricing differ.

$/day is over the full window — cash hours are part of the policy.

A single streak spanning the whole window IS E010's committed race run;
tests/test_e011_contracts.py asserts float-consistent reproduction at all
three gas points.

Outputs: out/stage2_results.json, out/stage2_streaks_<arm>.csv (central).
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

import common11 as C


def run_streaks(arm: dict, runs, hs: np.ndarray, point_name: str):
    """Simulate the given streaks under one coupled gas point. Returns
    (total_bucket_dict, months, per-streak rows, max_gap, n_sim)."""
    total: dict = {}
    months: dict[str, dict] = {}
    rows = []
    max_gap = 0.0
    point = C.ENVELOPE_BY_NAME[point_name]
    with C.chain_gas(point_name):
        for (i, j) in runs:
            r = C.simulate_streak(arm, int(hs[i]), int(hs[j]) + 3600)
            if r is None:
                continue
            C.add_bucket(total, r.total)
            for lab, b in r.months.items():
                months.setdefault(lab, {})
                C.add_bucket(months[lab], b)
            gap = r.checks["lp_value_abs_gap_usd"]
            max_gap = max(max_gap, gap)
            rows.append({
                "start_utc": str(pd.Timestamp(int(hs[i]), unit="s", tz="UTC")),
                "end_utc": str(pd.Timestamp(int(hs[j]) + 3600, unit="s",
                                            tz="UTC")),
                "hours": r.total.hours,
                "n_recenters": r.total.n_recenters,
                "lp_fees_usd": r.total.lp_fees_usd,
                "funding_usd": r.total.funding_usd,
                "onchain_cost_usd": r.total.onchain_cost_usd,
                "rehedge_notional_usd": r.total.rehedge_notional_usd,
                "net_usd": r.total.net_usd(point),
                "lp_value_abs_gap_usd": gap,
            })
    return total, months, rows, max_gap


def main() -> int:
    stage1 = C.read_json(C.OUT / "stage1_results.json")
    spec, swaps, funding, marks = C.load_all()
    days = stage1["window"]["days"]

    payload = {
        "experiment": "E011", "stage": 2,
        "cost_model_version": stage1["cost_model_version"],
        "envelope_version": stage1["envelope_version"],
        "window": stage1["window"],
        "policy": "stage-1 DP selection at the coupled CENTRAL point, "
                  "re-simulated exactly (lag1h_rh1h inside streaks, cash "
                  "outside); the same streaks re-run under each coupled gas "
                  "point and priced at the same-named HPL point",
        "arms": {},
    }

    for arm in C.arms():
        label = arm["label"]
        t0 = time.time()
        hours = pd.read_csv(C.OUT / f"stage1_hours_{label}.csv")
        held = hours["held_central"].to_numpy(bool)
        hs = hours["hour_epoch"].to_numpy(np.int64)
        runs = C.E6O.streaks_of(held)

        pts = {}
        central_rows = None
        max_gap_all = 0.0
        n_sim = 0
        for pn in C.POINTS:
            total, months, rows, max_gap = run_streaks(arm, runs, hs, pn)
            point = C.ENVELOPE_BY_NAME[pn]
            v = C.net_usd(total, point) if total else 0.0
            pts[pn] = {"net_usd": v, "per_day_usd": v / days}
            max_gap_all = max(max_gap_all, max_gap)
            if pn == "central":
                central_rows = rows
                n_sim = len(rows)
                central_total = total
                central_months = months
        pd.DataFrame(central_rows).to_csv(
            C.OUT / f"stage2_streaks_{label}.csv", index=False)

        s1c = stage1["arms"][label]["points"]["central"]["value_usd"]
        payload["arms"][label] = {
            "label": label, "width_pct": arm["actual_pct"],
            "n_streaks_selected": len(runs),
            "n_streaks_simulated": n_sim,
            "held_hours_simulated": central_total.get("hours", 0.0),
            "held_frac": central_total.get("hours", 0.0) / (days * 24.0),
            "max_lp_value_abs_gap_usd": max_gap_all,
            "points": pts,
            "stage1_central_usd": s1c,
            "stage2_over_stage1_central":
                (pts["central"]["net_usd"] / s1c) if s1c else None,
            "capture_bar_10pct":
                (C.TARGET_10PCT / pts["central"]["per_day_usd"])
                if pts["central"]["per_day_usd"] > 0 else None,
            "total": central_total,
            "months": {k: {**central_months[k],
                           "net_central_usd": C.net_usd(
                               central_months[k],
                               C.ENVELOPE_BY_NAME["central"])}
                       for k in sorted(central_months)},
        }
        c = pts["central"]
        print(f"{label:<26s} exact central ${c['net_usd']:+9.2f} "
              f"(${c['per_day_usd']:+.3f}/d) over {n_sim} streaks, "
              f"{central_total.get('hours', 0.0):.0f}h held, retains "
              f"{payload['arms'][label]['stage2_over_stage1_central']:.1%} "
              f"of stage-1 [opt {pts['optimistic']['per_day_usd']:+.3f} "
              f"pess {pts['pessimistic']['per_day_usd']:+.3f}] "
              f"max gap {max_gap_all:.2e}  {time.time()-t0:.0f}s", flush=True)

    best = max(payload["arms"].values(),
               key=lambda a: a["points"]["central"]["per_day_usd"])
    payload["best_arm_central"] = best["label"]
    payload["supported_net_clause_fires"] = bool(
        best["points"]["central"]["per_day_usd"] >= C.TARGET_20PCT)
    C.write_json(C.OUT / "stage2_results.json", payload)
    print(f"wrote {C.OUT/'stage2_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
