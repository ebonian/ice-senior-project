#!/usr/bin/env python3
"""E011 coarseness table — M001 §2's constrained oracle, transferred.

    nix develop .#gate1 -c python backtest_model_server/e011/coarse11.py

Same stage-1 payoffs and coupled-central switch costs as oracle11.py, DP
extended with the M001 §2 constraint set (e007/constrained_oracle.py's
dp_minhold / dp_grain, reused by import), each constrained selection then
re-simulated exactly (exact11.run_streaks, central point). Answers: is the
viable decision scale still 1–6h under mainnet gas, or has the ~$12.7
round-trip pushed the whole surface coarse?

Descriptive input to the REPORT (mandatory, non-deciding — pre-registered).

Output: out/coarse_results.json.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

import common11 as C
import oracle11 as O
import exact11 as X

CONSTRAINTS = (("minhold_6h", "minhold", 6), ("minhold_12h", "minhold", 12),
               ("minhold_24h", "minhold", 24), ("grain_4h", "grain", 4),
               ("grain_24h", "grain", 24))


def main() -> int:
    stage1 = C.read_json(C.OUT / "stage1_results.json")
    stage2 = C.read_json(C.OUT / "stage2_results.json")
    days = stage1["window"]["days"]

    payload = {"experiment": "E011", "part": "coarseness",
               "constraint_set": "M001 §2 (min-hold 6/12/24h, grain 4/24h)",
               "point": "central (coupled)", "arms": {}}

    for arm in C.arms():
        label = arm["label"]
        hours = pd.read_csv(C.OUT / f"stage1_hours_{label}.csv")
        payoff = hours["payoff_usd"].to_numpy()
        hs = hours["hour_epoch"].to_numpy(np.int64)
        enter, exit_ = O.switch_costs(hours, "central")

        rec = {"unconstrained": {
            "stage1_value_usd":
                stage1["arms"][label]["points"]["central"]["value_usd"],
            "stage1_per_day":
                stage1["arms"][label]["points"]["central"]["per_day_usd"],
            "stage2_net_usd":
                stage2["arms"][label]["points"]["central"]["net_usd"],
            "stage2_per_day":
                stage2["arms"][label]["points"]["central"]["per_day_usd"],
            "held_frac": stage2["arms"][label]["held_frac"],
            "n_streaks": stage2["arms"][label]["n_streaks_simulated"],
        }, "constraints": {}}

        for cname, kind, param in CONSTRAINTS:
            t0 = time.time()
            if kind == "minhold":
                value, held = C.E7C.dp_minhold(payoff, enter, exit_, param)
            else:
                value, held = C.E7C.dp_grain(payoff, enter, exit_, hs, param)
            runs = C.E6O.streaks_of(held)
            total, _, rows, max_gap = X.run_streaks(arm, runs, hs, "central")
            net = C.net_usd(total, C.ENVELOPE_BY_NAME["central"]) if total else 0.0
            rec["constraints"][cname] = {
                "stage1_value_usd": float(value),
                "stage1_per_day": float(value / days),
                "stage2_net_usd": net,
                "stage2_per_day": net / days,
                "held_frac": float(held.mean()),
                "n_streaks": len(runs),
                "max_lp_value_abs_gap_usd": max_gap,
            }
            cc = rec["constraints"][cname]
            print(f"{label:<26s} {cname:<11s} UB ${cc['stage1_per_day']:+7.3f}/d "
                  f"exact ${cc['stage2_per_day']:+7.3f}/d "
                  f"held {cc['held_frac']*100:5.1f}% in {len(runs):>3} streaks "
                  f"{time.time()-t0:.0f}s", flush=True)
        payload["arms"][label] = rec

    C.write_json(C.OUT / "coarse_results.json", payload)
    print(f"wrote {C.OUT/'coarse_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
