#!/usr/bin/env python3
"""H1 — is the harness's fee/hedge attribution off by one hour?

04-backtest-design.md §2.2 flags this as a strong reading of the code that had
never been executed, and §10 makes settling it Phase 1's first task:

    "A unit test on a synthetic two-hour window with swaps in only one hour
     settles it in an hour."

This is that test. `simulate_step` documents its own contract as

    "During [prev_step -> this_step] the price moved prev_price -> current_price.
     We first credit/debit P&L for that interval."

so a step stamped 11:00 prices the interval [10:00, 11:00). Swaps in that
interval live in the bucket keyed 10:00, because `HourlySwapData` buckets with
`dt.floor("h")`. The code reads the bucket keyed by *this* step's hour.

Run:  nix develop .#gate1 -c python backtest_model_server/gate1/tests/test_h1_alignment.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import harness as H  # noqa: E402

bt = H.bt

H10 = pd.Timestamp("2026-05-14 10:00:00", tz="UTC")
H11 = pd.Timestamp("2026-05-14 11:00:00", tz="UTC")

PRICE = 2255.0
POOL_L = 6.44e18
N_SWAPS = 40
SWAP_USD = 5_000.0


def make_swap_data(busy_hour: pd.Timestamp) -> "H.HourlySwapData":
    """Swaps in exactly one hour; the other hour is empty."""
    sd = H.HourlySwapData(18, 6)
    v3_tick = H.human_tick_to_v3_tick(H.price_to_tick(PRICE), 18, 6)
    for hour in (H10, H11):
        n = N_SWAPS if hour == busy_hour else 0
        sd.swap_prices_per_hour[hour] = np.full(n, PRICE, dtype=np.float64)
        sd.swap_amounts_per_hour[hour] = np.full(n, SWAP_USD, dtype=np.float64)
        sd.swap_liquidity_per_hour[hour] = np.full(n, POOL_L, dtype=np.float64)
        sd.swap_ticks_per_hour[hour] = np.full(n, v3_tick, dtype=np.int64)
        sd.swap_time_seconds_per_hour[hour] = np.linspace(0, 3500, n) if n else np.array([])
        sd.pool_liquidity_per_hour[hour] = POOL_L if n else 0.0
        sd.volume_per_hour[hour] = SWAP_USD * n
    return sd


def run_step(swap_data) -> dict:
    """One HOLD step stamped 11:00, pricing the interval [10:00, 11:00)."""
    pl = H.tick_to_price(H.price_to_tick(PRICE) - 50)
    pu = H.tick_to_price(H.price_to_tick(PRICE) + 50)
    L = H.compute_liquidity_from_capital(1000.0, PRICE, pl, pu)
    state = {
        "has_position": True, "liquidity": L,
        "price_lower": pl, "price_upper": pu,
        "width": 10, "lower_tick": H.price_to_tick(pl), "upper_tick": H.price_to_tick(pu),
        "portfolio_value_usd": 1000.0, "initial_capital_usd": 1000.0,
        "hours_since_rebalance": 1.0, "accumulated_fees": 0.0,
        "cumulative_hedge_pnl": 0.0, "cumulative_funding": 0.0,
        "entry_price": PRICE,
    }
    cfg = {"pool_fee": 0.0005, "gas_cost_usd": 0.03, "mev_slippage_pct": 0.0001,
           "funding_rate_annual": 0.048, "hedge_ratio": 1.0,
           "decimals0": 18, "decimals1": 6}
    _, rec = bt.simulate_step(
        step_idx=1, prev_price=PRICE, current_price=PRICE,
        # naive, as the harness main loop passes them: simulate_step does
        # `pd.Timestamp(timestamp, tz="UTC")`, which raises on tz-aware input.
        timestamp=datetime(2026, 5, 14, 11, 0),
        action_label="HOLD", lp_range=None, prev_state=state, cfg=cfg,
        swap_data=swap_data,
    )
    return rec


def main() -> int:
    print(__doc__.split("Run:")[0].strip())
    print("\n" + "=" * 74)

    fee_when_busy_hour_is_the_priced_interval = run_step(make_swap_data(H10))["fee_usd"]
    fee_when_busy_hour_is_the_next_hour = run_step(make_swap_data(H11))["fee_usd"]

    print(f"step stamped 11:00 prices the interval [10:00, 11:00)")
    print(f"  swaps in 10:00 bucket (the priced interval): fee = ${fee_when_busy_hour_is_the_priced_interval:.6f}")
    print(f"  swaps in 11:00 bucket (the hour AFTER)     : fee = ${fee_when_busy_hour_is_the_next_hour:.6f}")

    ok = True
    if fee_when_busy_hour_is_the_priced_interval == 0.0 and fee_when_busy_hour_is_the_next_hour > 0.0:
        print("\nH1 CONFIRMED: the step earned $0 from the swaps inside the interval it")
        print("priced, and earned the full fee from swaps that happened after it.")
        print("`hour_ts = pd.Timestamp(timestamp).floor('h')` reads bucket t; the")
        print("interval [t-1, t) lives in bucket t-1.")
    else:
        print("\nH1 NOT reproduced — attribution appears aligned.")
        ok = False

    # The same index drives hedge P&L attribution.
    hedge_busy_10 = run_step(make_swap_data(H10))["hedge_pnl_usd"]
    hedge_busy_11 = run_step(make_swap_data(H11))["hedge_pnl_usd"]
    print(f"\nhedge path (same index): busy@10:00 -> {hedge_busy_10:.6f}, "
          f"busy@11:00 -> {hedge_busy_11:.6f}")

    # And the control the design doc names: time_in_range uses the PREVIOUS hour,
    # so the two conventions genuinely disagree inside one file.
    print("\ncontrol — `main()` computes time_in_range from `timestamps[step_idx-1]`")
    print("(the previous hour) while `simulate_step` uses this step's hour. One of")
    print("the two conventions is wrong; this test shows which.")

    print("=" * 74)
    print("RESULT:", "H1 CONFIRMED (bug is real)" if ok else "INCONCLUSIVE")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
