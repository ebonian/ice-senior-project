#!/usr/bin/env python3
"""E011 wick-honesty check on the ORACLE'S HELD HOURS (K15, mandatory).

    nix develop .#gate1 -c python backtest_model_server/e011/wick11.py

E010 §3's lesson: an aggregate share gate cannot see a fee line carried by a
few swaps through momentarily near-empty ticks — and a timing oracle is a
wick-seeking machine by construction, so the check must run on the held
set, not the pool. Per arm: rank held-hour swaps by vol_usd/pool_liquidity
(the fee-credit weight in the small-share regime, position-independent) and
report top-10/top-50 mass, the same for the full window as reference, and
the top-10 stage-1 fee hours' share of held fees.

Output: out/wick_results.json.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import common11 as C


def conc(weights: np.ndarray) -> dict:
    tot = float(weights.sum())
    w = np.sort(weights)[::-1]
    return {
        "n_swaps": int(len(w)),
        "top10_share": float(w[:10].sum() / tot) if tot else None,
        "top50_share": float(w[:50].sum() / tot) if tot else None,
    }


def main() -> int:
    spec, swaps, funding, marks = C.load_all()
    vol = swaps["volume_usd"].to_numpy(np.float64)
    liq = swaps["pool_liquidity"].to_numpy(np.float64)
    weight = vol / liq
    hour_key = swaps["timestamp"].to_numpy(np.int64) // 3600

    payload = {"experiment": "E011", "part": "wick-honesty (K15)",
               "metric": "vol_usd / pool_liquidity per swap",
               "full_window": conc(weight), "arms": {}}

    for arm in C.arms():
        label = arm["label"]
        hrs = pd.read_csv(C.OUT / f"stage1_hours_{label}.csv")
        held = hrs["held_central"].to_numpy(bool)
        held_keys = set((hrs["hour_epoch"].to_numpy(np.int64) // 3600)[held])
        in_held = np.array([k in held_keys for k in hour_key])

        fees = hrs["fees_usd"].to_numpy()
        hf = np.sort(fees[held])[::-1]
        tot_f = float(hf.sum())
        top_hours = pd.DataFrame({
            "hour_epoch": hrs["hour_epoch"][held], "fees_usd": fees[held]})
        top_hours = top_hours.nlargest(5, "fees_usd")

        payload["arms"][label] = {
            "held_swaps": conc(weight[in_held]),
            "held_fee_hours": {
                "n_held_hours": int(held.sum()),
                "top10_hours_fee_share":
                    float(hf[:10].sum() / tot_f) if tot_f else None,
                "top50_hours_fee_share":
                    float(hf[:50].sum() / tot_f) if tot_f else None,
                "top5_hours_utc": [
                    {"utc": str(pd.Timestamp(int(r.hour_epoch), unit="s",
                                             tz="UTC")),
                     "fees_usd": round(float(r.fees_usd), 2)}
                    for r in top_hours.itertuples()],
            },
        }
        a = payload["arms"][label]
        print(f"{label:<26s} held top-10 swap weight "
              f"{a['held_swaps']['top10_share']*100:5.2f}% "
              f"(full-window {payload['full_window']['top10_share']*100:.2f}%)"
              f"  top-10 fee-hours {a['held_fee_hours']['top10_hours_fee_share']*100:5.2f}%",
              flush=True)

    C.write_json(C.OUT / "wick_results.json", payload)
    print(f"wrote {C.OUT/'wick_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
