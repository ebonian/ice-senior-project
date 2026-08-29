"""Per-swap V3 fee accrual over an arbitrary time slice.

This is the harness's `compute_fee` primary path with two changes and nothing
else:

  1. It runs over a caller-supplied swap slice instead of an `hour_ts` bucket
     lookup. That removes the H1 misalignment at the source rather than patching
     the index, and it lets a cycle start at 05:02:06 instead of 05:00:00.
  2. LP bounds are taken as exact on-chain ticks when the caller has them (mode-A
     replay reads `applied_tick_lower`/`applied_tick_upper` straight from
     `rebalance-history`), instead of the price->tick round-trip that costs a
     tick of precision (finding M3).

The arithmetic gains exactly one term, and it is not a tuning knob:

    fee_j = amount_j x pool_fee x LP_FEE_SHARE x L_raw/(L_pool,j + L_raw) x frac_j

`LP_FEE_SHARE` is the fraction of the swap fee that reaches liquidity providers
rather than the Uniswap treasury. This pool runs with `slot0().feeProtocol =
0x44` — a denominator of 4 on both tokens — so the protocol skims 1/4 and LPs
receive 75%. The harness (and the training environment it inherits from) credits
the full 5 bps, overstating LP fee income by 1/0.75 = 33.3% everywhere. See
gate1/REPORT.md finding F1; verified on-chain and unchanged across the trial
window (no `SetFeeProtocol` event in blocks 460M-465M).

`tests/test_fee_equivalence.py` pins change (1) by asserting this function equals
`compute_fee` to 1e-12 when handed exactly one hour bucket in harness-compat mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import harness as H
from .cost_model import LP_FEE_SHARE


@dataclass
class FeeAccrual:
    fee_usd: float = 0.0
    n_swaps: int = 0
    n_swaps_in_range: int = 0
    volume_usd: float = 0.0
    volume_in_range_usd: float = 0.0
    mean_liquidity_share: float = 0.0
    time_in_range_frac: float = 0.0
    per_hour: dict = field(default_factory=dict)   # hour_ts -> fee_usd
    cumulative: list = field(default_factory=list)  # [(ts, cum_fee)]


def accrue_fees(
    swaps: pd.DataFrame,
    L_human: float,
    lower_v3_tick: int,
    upper_v3_tick: int,
    price_lower: float,
    price_upper: float,
    prev_price: float,
    prev_v3_tick: int,
    pool_fee: float = 0.0005,
    liquidity_scale: float = 1e12,
    lp_fee_share: float = LP_FEE_SHARE,
    track_path: bool = True,
) -> FeeAccrual:
    """Fee earned by liquidity `L_human` over the swaps in `swaps`.

    `prev_price` / `prev_v3_tick` are the pool state immediately before the
    first swap in the slice — for a cycle, the state at mint.
    """
    out = FeeAccrual()
    if L_human <= 0 or len(swaps) == 0:
        return out

    L_raw = L_human * liquidity_scale
    prices = swaps["price"].to_numpy(dtype=np.float64)
    amounts = swaps["volume_usd"].to_numpy(dtype=np.float64)
    liqs = swaps["pool_liquidity"].to_numpy(dtype=np.float64)
    ticks = swaps["v3_tick"].to_numpy(dtype=np.int64)
    times = swaps["ts"].to_numpy()

    total_fee = 0.0
    share_sum = 0.0
    in_range_swaps = 0
    vol_in_range = 0.0
    per_hour: dict = {}
    cumulative = []

    hours = pd.to_datetime(swaps["ts"]).dt.floor("h").to_numpy() if track_path else None

    for j in range(len(amounts)):
        p_before = prices[j - 1] if j > 0 else prev_price
        p_after = prices[j]

        if (p_before < price_lower and p_after < price_lower) or (
            p_before > price_upper and p_after > price_upper
        ):
            if track_path:
                cumulative.append((times[j], total_fee))
            continue

        pool_L_j = liqs[j]
        ls_j = L_raw / (pool_L_j + L_raw) if pool_L_j > 0 else 0.0

        t_before = int(ticks[j - 1]) if j > 0 else int(prev_v3_tick)
        t_after = int(ticks[j])
        in_range_frac = H._tick_in_range_fraction(
            t_before, t_after, lower_v3_tick, upper_v3_tick
        )

        fee_j = max(0.0, amounts[j] * pool_fee * lp_fee_share * ls_j * in_range_frac)
        total_fee += fee_j
        share_sum += ls_j
        if in_range_frac > 0:
            in_range_swaps += 1
            vol_in_range += amounts[j] * in_range_frac

        if track_path:
            h = hours[j]
            per_hour[h] = per_hour.get(h, 0.0) + fee_j
            cumulative.append((times[j], total_fee))

    n = len(amounts)
    out.fee_usd = total_fee
    out.n_swaps = n
    out.n_swaps_in_range = in_range_swaps
    out.volume_usd = float(amounts.sum())
    out.volume_in_range_usd = vol_in_range
    out.mean_liquidity_share = share_sum / n if n else 0.0
    out.time_in_range_frac = float(
        np.mean((ticks >= lower_v3_tick) & (ticks <= upper_v3_tick))
    )
    out.per_hour = per_hour
    out.cumulative = cumulative
    return out


def accrue_fees_harness_compat(
    swaps: pd.DataFrame,
    L_human: float,
    price_lower: float,
    price_upper: float,
    prev_price: float,
    pool_fee: float = 0.0005,
    liquidity_scale: float = 1e12,
    decimals0: int = 18,
    decimals1: int = 6,
    lp_fee_share: float = 1.0,
) -> float:
    """Same accrual, but deriving LP ticks the way `compute_fee` does.

    Exists only so the equivalence test can isolate the slicing change from the
    tick-precision change (M3). Defaults `lp_fee_share` to 1.0 so it reproduces
    the harness bit-for-bit, protocol-fee bug included. Not used by the replay.
    """
    lo = H.human_tick_to_v3_tick(H.price_to_tick(price_lower), decimals0, decimals1)
    hi = H.human_tick_to_v3_tick(H.price_to_tick(price_upper), decimals0, decimals1)
    opening = H.human_tick_to_v3_tick(H.price_to_tick(prev_price), decimals0, decimals1)
    return accrue_fees(
        swaps, L_human, lo, hi, price_lower, price_upper,
        prev_price, opening, pool_fee, liquidity_scale,
        lp_fee_share=lp_fee_share, track_path=False,
    ).fee_usd
