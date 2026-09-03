#!/usr/bin/env python3
"""Per-swap fee-credit honesty diagnostic (the K9 caveat, quantified).

    nix develop .#gate1 -c python backtest_model_server/e010/wick_diag.py

Gate (d) bounds the AGGREGATE implied share; it cannot see a fee line carried
by a few swaps that execute through momentarily near-empty ticks, where the
engine's L/(L_pool + L) credit approaches 100% of that swap's fee. This
script measures, per venue:

  - the race's own monthly LP-fee decomposition (from results.json), and
  - the convention-free concentration of Σ vol_usd / pool_liquidity —
    the per-swap fee-credit weight in the small-share regime, independent of
    our position's L — top-10 / top-50 mass, plus the top swap events.

It changes no gate and no verdict; it is the pre-registered K9 caveat made
quantitative for the two honest-headroom venues, written to
out/wick_sensitivity.json and cited by REPORT.md.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

E010 = Path(__file__).resolve().parent
sys.path.append(str(E010))


def main() -> int:
    marks = pd.read_csv(E010.parent / "e005" / "data" / "marks"
                        / "binance_ethusdt_1h.csv")
    mt = marks["open_time_ms"].to_numpy(np.int64) // 1000
    mv = marks["open"].to_numpy(np.float64)

    out = {}
    for slug in ("m_wsteth_weth_0p01", "m_link_weth_0p30"):
        d = E010 / "data" / "swaps" / slug
        df = pd.concat([pd.read_parquet(f) for f in sorted(d.glob("*.parquet"))
                        if not f.name.endswith(".raw.parquet")],
                       ignore_index=True)
        df = df.sort_values(["block_number", "log_index"]).reset_index(drop=True)
        idx = np.searchsorted(mt, df["timestamp"].to_numpy(np.int64)
                              // 3600 * 3600, side="right") - 1
        vol = df["vol_token1"].to_numpy() * mv[idx]
        ratio = vol / df["pool_liquidity"].to_numpy()
        o = np.argsort(ratio)[::-1]
        tot = float(ratio.sum())
        top = []
        for i in o[:10]:
            top.append({
                "utc": str(pd.Timestamp(int(df["timestamp"].iloc[i]),
                                        unit="s", tz="UTC")),
                "vol_usd": round(float(vol[i]), 0),
                "pool_liquidity": float(df["pool_liquidity"].iloc[i]),
                "tick": int(df["tick"].iloc[i]),
                "weight_pct_of_total": round(float(ratio[i]) / tot * 100, 2),
            })
        rr = json.loads((E010 / "out" / slug
                         / "lag1h_rh1h_cap10000_gas-central"
                         / "results.json").read_text())
        monthly_fees = {
            a["arm"]: {k: round(v["lp_fees_usd"], 2)
                       for k, v in a["months"].items()}
            for a in rr["arms"] if a["arm"] != "always_cash"}
        out[slug] = {
            "n_swaps": int(len(df)),
            "median_tick": float(np.median(df["tick"])),
            "vol_over_poolL_top10_pct": round(float(ratio[o[:10]].sum())
                                              / tot * 100, 2),
            "vol_over_poolL_top50_pct": round(float(ratio[o[:50]].sum())
                                              / tot * 100, 2),
            "top_swaps": top,
            "race_monthly_lp_fees_usd": monthly_fees,
        }
        print(f"{slug}: top10 weight {out[slug]['vol_over_poolL_top10_pct']}% "
              f"top50 {out[slug]['vol_over_poolL_top50_pct']}%")
        w83 = [a for a in monthly_fees if "8.3" in a]
        if w83:
            print(f"  monthly fees {w83[0]}: {monthly_fees[w83[0]]}")
    (E010 / "out" / "wick_sensitivity.json").write_text(json.dumps(out, indent=2))
    print("wrote out/wick_sensitivity.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
