#!/usr/bin/env python3
"""Prove E003's swap data is the same chain data Gate 1 reproduced T5 against.

    nix develop .#gate1 -c python backtest_model_server/e003/tests/test_vs_gate1_t5.py

E003 pulls whole months; gate1 pulled a padded 27-hour window around each trial.
T5 (2026-05-14/15) sits inside E003's `2026-05.parquet`, so the two pulls overlap
and can be compared where it matters rather than assumed equivalent.

For each of T5's 8 recorded cycles this re-runs `gate1/engine/fee_engine.accrue_fees`
with gate1's own liquidity, ticks and block range — changing ONLY which parquet
the swaps come from — and requires the fee to match gate1's published
`fees_modelled_usd`. `accrue_fees` never reads timestamps in this mode, so a
match is a statement about the swap set itself: same logs, same prices, same pool
liquidity, same ticks. A mismatch would mean one of the two pulls is missing
swaps, which is exactly what issue Y warns about for B2-sourced data.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

E003 = Path(__file__).resolve().parents[1]
GATE1 = E003.parent / "gate1"
sys.path.insert(0, str(GATE1))
sys.path.insert(0, str(E003))
from engine import fee_engine, harness as H  # noqa: E402
import race as R  # noqa: E402

POOL_FEE = 0.0005
LIQ_SCALE = H.liquidity_scale(18, 6)
TOL_REL = 1e-9


def main(swap_dir: Path | None = None) -> int:
    cyc = pd.read_csv(GATE1 / "out" / "T5" / "cycles.csv")
    g1 = pd.read_parquet(GATE1 / "data" / "rpc" / "T5" / "swaps.parquet")
    e3 = R.load_swaps("2026-05-14", "2026-05-16", swap_dir)

    b0, b1 = int(cyc["mint_block"].min()), int(cyc["burn_block"].max())
    g1b = g1["block_number"].astype("int64")
    g1_keys = set(zip(g1b[(g1b >= b0) & (g1b <= b1)].tolist(),
                      g1.loc[(g1b >= b0) & (g1b <= b1), "log_index"].astype(int).tolist()))
    m = (e3["block_number"] >= b0) & (e3["block_number"] <= b1)
    e3_keys = set(zip(e3.loc[m, "block_number"].tolist(),
                      e3.loc[m, "log_index"].astype(int).tolist()))
    print(f"cycle-span blocks {b0:,}..{b1:,}")
    print(f"  gate1 swaps {len(g1_keys):,}   e003 swaps {len(e3_keys):,}")
    print(f"  in gate1 only: {len(g1_keys - e3_keys):,}   "
          f"in e003 only: {len(e3_keys - g1_keys):,}")
    set_ok = g1_keys == e3_keys

    print("\nper-cycle LP fee, gate1 parquet vs e003 parquet, same accrue_fees call:")
    print(f"{'cyc':>4s} {'gate1 $':>10s} {'e003 $':>10s} {'rel err':>12s} {'swaps':>7s}")
    fails = []
    for _, r in cyc.iterrows():
        mb, bb = int(r["mint_block"]), int(r["burn_block"])
        prior = e3[e3["block_number"] <= mb]
        t_entry = int(prior["v3_tick"].iloc[-1]) if len(prior) else int(e3["v3_tick"].iloc[0])
        sl = e3[(e3["block_number"] > mb) & (e3["block_number"] <= bb)]
        acc = fee_engine.accrue_fees(
            sl, float(r["L_human"]), int(r["lower_tick"]), int(r["upper_tick"]),
            float(r["price_lower"]), float(r["price_upper"]),
            prev_price=float(r["p_entry_chain"]), prev_v3_tick=t_entry,
            pool_fee=POOL_FEE, liquidity_scale=LIQ_SCALE, track_path=False,
        )
        want = float(r["fees_modelled_usd"])
        rel = abs(acc.fee_usd - want) / abs(want) if want else 0.0
        ok = rel <= TOL_REL and acc.n_swaps == int(r["n_swaps"])
        if not ok:
            fails.append(int(r["cycle"]))
        print(f"{int(r['cycle']):>4d} {want:>10.6f} {acc.fee_usd:>10.6f} "
              f"{rel:>12.2e} {acc.n_swaps:>7,}"
              f"{'' if ok else '   <-- MISMATCH (gate1 n_swaps ' + str(int(r['n_swaps'])) + ')'}")

    print()
    if not set_ok:
        print("FAIL: the two pulls disagree on which swaps exist in the window")
    if fails:
        print(f"FAIL: cycles {fails} do not reproduce gate1's fee")
    if fails or not set_ok:
        return 1
    print("PASS: e003's month-scale pull is swap-for-swap identical to gate1's "
          "trial-window pull, and reproduces all 8 T5 cycle fees exactly")
    return 0


if __name__ == "__main__":
    _ap = argparse.ArgumentParser()
    _ap.add_argument("--swap-dir", default=None,
                     help="override e003/data/swaps (used to self-test the glue "
                          "against a copy of gate1's own parquet)")
    _a = _ap.parse_args()
    raise SystemExit(main(Path(_a.swap_dir) if _a.swap_dir else None))
