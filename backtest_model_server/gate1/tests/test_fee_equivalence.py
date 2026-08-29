#!/usr/bin/env python3
"""gate1's slice-based fee engine must equal the harness's `compute_fee`.

The design brief is explicit that the harness's per-swap V3 fee arithmetic was
independently verified and must be extended around, not rewritten. gate1 changes
only *which swaps* the sum runs over (a cycle slice instead of an hour bucket).
This test pins that: handed exactly one hour bucket, in harness-compat mode
(LP ticks derived by the same price->tick round trip), the two agree to 1e-12.

If this ever fails, gate1 has drifted from the verified engine and every Gate 1
number is suspect.

Run:  nix develop .#gate1 -c python backtest_model_server/gate1/tests/test_fee_equivalence.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import fee_engine, harness as H, swaps as SW  # noqa: E402

B2_SWAPS = Path(__file__).resolve().parents[1] / "data" / "b2" / "swaps"
LIQ_SCALE = H.liquidity_scale(18, 6)
POOL_FEE = 0.0005


def build_hourly(df: pd.DataFrame) -> "H.HourlySwapData":
    """Same bucketing the harness does, from an already-decoded frame."""
    sd = H.HourlySwapData(18, 6)
    df = df.copy()
    df["hour"] = df["ts"].dt.floor("h")
    for hour, g in df.groupby("hour"):
        sd.swap_prices_per_hour[hour] = g["price"].to_numpy(np.float64)
        sd.swap_amounts_per_hour[hour] = g["volume_usd"].to_numpy(np.float64)
        sd.swap_liquidity_per_hour[hour] = g["pool_liquidity"].to_numpy(np.float64)
        sd.swap_ticks_per_hour[hour] = g["v3_tick"].to_numpy(np.int64)
        sd.swap_time_seconds_per_hour[hour] = (
            (g["ts"] - hour).dt.total_seconds().to_numpy(np.float64)
        )
        sd.pool_liquidity_per_hour[hour] = float(np.median(g["pool_liquidity"]))
        sd.volume_per_hour[hour] = float(g["volume_usd"].sum())
    return sd


def main() -> int:
    df = SW.load_swaps(
        pd.Timestamp("2026-05-14 00:00", tz="UTC"),
        pd.Timestamp("2026-05-15 00:00", tz="UTC"),
        swap_dir=B2_SWAPS,
    )
    sd = build_hourly(df)
    hours = sorted(sd.swap_prices_per_hour)
    print(f"{len(df)} swaps across {len(hours)} hour buckets from B2 2026-05-14")

    worst = 0.0
    n = 0
    print(f"\n{'hour':>16s} {'swaps':>6s} {'harness $':>12s} {'gate1 $':>12s} {'|diff|':>10s}")
    for hour in hours:
        g = df[df["ts"].dt.floor("h") == hour]
        if len(g) == 0:
            continue
        p0 = float(g["price"].iloc[0])
        # A W10 range centred on the hour's opening price, the live policy's shape.
        centre = H.price_to_tick(p0)
        pl = H.tick_to_price(centre - 50)
        pu = H.tick_to_price(centre + 50)
        L = H.compute_liquidity_from_capital(1000.0, p0, pl, pu)

        a = H.compute_fee(sd, hour, p0, float(g["price"].iloc[-1]), L, pl, pu,
                          POOL_FEE, LIQ_SCALE)
        b = fee_engine.accrue_fees_harness_compat(
            g, L, pl, pu, prev_price=p0, pool_fee=POOL_FEE, liquidity_scale=LIQ_SCALE
        )
        d = abs(a - b)
        worst = max(worst, d)
        n += 1
        print(f"{str(hour)[:16]:>16s} {len(g):>6d} {a:>12.8f} {b:>12.8f} {d:>10.2e}")

    print(f"\nchecked {n} hour buckets; worst absolute difference {worst:.3e}")
    ok = worst < 1e-12
    print("RESULT:", "PASS — gate1 reproduces the verified engine exactly"
          if ok else f"FAIL — divergence {worst:.3e}")

    # Second half: show what the exact-tick path (M3 fix) changes, so the
    # difference is attributed rather than absorbed.
    print("\n--- effect of using exact on-chain ticks instead of the price->tick "
          "round trip (finding M3) ---")
    diffs = []
    for hour in hours[:8]:
        g = df[df["ts"].dt.floor("h") == hour]
        p0 = float(g["price"].iloc[0])
        centre = H.price_to_tick(p0)
        pl, pu = H.tick_to_price(centre - 50), H.tick_to_price(centre + 50)
        L = H.compute_liquidity_from_capital(1000.0, p0, pl, pu)
        compat = fee_engine.accrue_fees_harness_compat(
            g, L, pl, pu, prev_price=p0, pool_fee=POOL_FEE, liquidity_scale=LIQ_SCALE
        )
        lo_v3 = H.human_tick_to_v3_tick(centre - 50, 18, 6)
        hi_v3 = H.human_tick_to_v3_tick(centre + 50, 18, 6)
        exact = fee_engine.accrue_fees(
            g, L, lo_v3, hi_v3, pl, pu, prev_price=p0,
            prev_v3_tick=H.human_tick_to_v3_tick(centre, 18, 6),
            pool_fee=POOL_FEE, liquidity_scale=LIQ_SCALE,
            # lp_fee_share=1.0 so this isolates the tick-precision change; the
            # protocol-fee term (finding F1) is tested by the replay, not here.
            lp_fee_share=1.0, track_path=False,
        ).fee_usd
        if compat > 0:
            diffs.append((exact - compat) / compat * 100)
        print(f"{str(hour)[:16]:>16s} compat {compat:.8f}  exact-ticks {exact:.8f}  "
              f"{((exact-compat)/compat*100 if compat else 0):+.4f}%")
    if diffs:
        print(f"mean effect of the M3 fix: {np.mean(diffs):+.4f}% "
              f"(range {min(diffs):+.4f}% .. {max(diffs):+.4f}%)")

    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
