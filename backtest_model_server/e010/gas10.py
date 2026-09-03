#!/usr/bin/env python3
"""Build the measured per-chain gas envelope (M004 §2.2, pre-registered).

    nix develop .#gate1 -c python backtest_model_server/e010/gas10.py

Construction, frozen in the E010 pre-registration before any race:

    $/tx(point) = (basefee_pctile + tip) gwei x 250k gas x ETH_USD_mean / 1e9

with (p25 + 0.02) / (p50 + 0.05) / (p95 + 0.10) gwei for optimistic /
central / pessimistic, basefee percentiles over the window's own anchor
headers (derive_blocks.py), 250k blended gas per tx (mint 300-450k,
burn+collect 200-300k, swap 120-180k against the frozen 3-tx-per-rebalance /
2-per-exit action model), and the window-mean ETH mark from E005's committed
Binance CSV. Base adds a $0.005/tx L1-data adder. Arbitrum stays at the
frozen $0.0101/tx and is recorded here only for comparison.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

E010 = Path(__file__).resolve().parent
sys.path.insert(0, str(E010))
import registry as R  # noqa: E402

GAS_UNITS_PER_TX = 250_000
TIPS_GWEI = {"optimistic": 0.02, "central": 0.05, "pessimistic": 0.10}
PCTS = {"optimistic": 25, "central": 50, "pessimistic": 95}
BASE_L1_ADDER_USD = 0.005


def eth_usd_window_mean() -> float:
    m = pd.read_csv(E010.parent / "e005" / "data" / "marks" / "binance_ethusdt_1h.csv")
    return float(m["open"].mean())


def main() -> int:
    eth_usd = eth_usd_window_mean()
    out = {"generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "construction": "E010 pre-registration validity gate (iii): "
                           "(basefee pctile + tip) x 250k gas x window-mean ETH USD",
           "gas_units_per_tx": GAS_UNITS_PER_TX,
           "eth_usd_window_mean": round(eth_usd, 2),
           "arbitrum_frozen_usd_per_tx": R.ARB_GAS_USD_PER_TX}
    for chain in ("mainnet", "base"):
        rows = []
        d = R.BLOCKS_DIR / chain
        for f in sorted(d.glob("*.basefees.csv")):
            rows.append(pd.read_csv(f))
        bf = pd.concat(rows, ignore_index=True)
        gwei = bf["base_fee_wei"].to_numpy(np.float64) / 1e9
        pct = {k: float(np.percentile(gwei, p)) for k, p in PCTS.items()}
        usd = {}
        for point in ("optimistic", "central", "pessimistic"):
            allin_gwei = pct[point] + TIPS_GWEI[point]
            usd_tx = allin_gwei * 1e-9 * GAS_UNITS_PER_TX * eth_usd
            if chain == "base":
                usd_tx += BASE_L1_ADDER_USD
            usd[point] = round(usd_tx, 6)
        out[chain] = {
            "n_basefee_samples": int(len(gwei)),
            "basefee_gwei": {"p25": round(pct["optimistic"], 6),
                             "p50": round(pct["central"], 6),
                             "p95": round(pct["pessimistic"], 6),
                             "mean": round(float(gwei.mean()), 6),
                             "max": round(float(gwei.max()), 6)},
            "tips_gwei": TIPS_GWEI,
            "l1_data_adder_usd": BASE_L1_ADDER_USD if chain == "base" else 0.0,
            "usd_per_tx": usd,
            "usd_per_recenter_4tx": {k: round(v * R.TX_PER_RECENTER, 6)
                                     for k, v in usd.items()},
        }
        print(f"{chain}: basefee p25/p50/p95 = {pct['optimistic']:.4f} / "
              f"{pct['central']:.4f} / {pct['pessimistic']:.4f} gwei "
              f"(n={len(gwei)}, max {gwei.max():.3f}) -> $/tx "
              f"{usd['optimistic']:.4f} / {usd['central']:.4f} / "
              f"{usd['pessimistic']:.4f}")
    R.GAS_ENVELOPE_FILE.parent.mkdir(parents=True, exist_ok=True)
    R.GAS_ENVELOPE_FILE.write_text(json.dumps(out, indent=2))
    print(f"eth_usd window mean {eth_usd:.2f}; wrote {R.GAS_ENVELOPE_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
