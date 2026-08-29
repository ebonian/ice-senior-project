"""Crystallized IL and basket delta, per LP cycle.

The harness already values a position with exact V3 math at both ends of every
interval, but only ever emits the difference as `lp_value_change_usd` — one
number that silently nets a short-gamma cost against a directional gain. Report
01 §5 showed what that costs: T5's "-$4.83 of accounting noise" is really
-$10.90 of real IL, +$8.52 of real delta offset, and about -$2.4 of genuine
residual. This module is the decomposition.

Per cycle, against the basket the position held at mint:

    IL_cycle      = V_position(P_exit) - V_hodl(basket_at_mint, P_exit)
    basket_delta  = V_hodl(basket_at_mint, P_exit) - V_position(P_entry)

IL is short-gamma cost that no hedge removes and that accrues strictly against
us. basket_delta is directional exposure the perp short is supposed to offset,
and is the "delta luck" that must be stripped before projecting. They have
opposite characters, so they are never netted here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict

from . import harness as H


@dataclass
class CycleIL:
    cycle: int
    mint_ts: str
    burn_ts: str
    lower_v3_tick: int
    upper_v3_tick: int
    price_lower: float
    price_upper: float
    price_entry: float
    price_exit: float
    v0_usd: float
    liquidity: float
    amount0_eth: float
    amount1_usdc: float
    v_position_exit: float
    v_hodl_exit: float
    il_usd: float
    basket_delta_usd: float
    lp_value_change_usd: float
    exited_range: bool
    frac_eth_at_entry: float
    frac_eth_at_exit: float


def position_amounts(price: float, price_lower: float, price_upper: float, L: float):
    """(token0 ETH, token1 USDC) held by liquidity L at `price`."""
    if L <= 0 or price <= 0:
        return 0.0, 0.0
    sp = math.sqrt(price)
    spl = math.sqrt(price_lower)
    spu = math.sqrt(price_upper)
    if price <= price_lower:
        return L * (1.0 / spl - 1.0 / spu), 0.0
    if price >= price_upper:
        return 0.0, L * (spu - spl)
    return L * (1.0 / sp - 1.0 / spu), L * (sp - spl)


def cycle_il(
    cycle: int,
    mint_ts,
    burn_ts,
    lower_v3_tick: int,
    upper_v3_tick: int,
    price_entry: float,
    price_exit: float,
    v0_usd: float,
    decimals0: int = 18,
    decimals1: int = 6,
) -> CycleIL:
    """Decompose one mint->burn cycle.

    `v0_usd` is the position's USD value just after the mint (the post-mint AUM
    snapshot in mode A). Liquidity is inverted from it, so the ledger is anchored
    on what the bot actually deployed rather than on nominal capital.
    """
    price_lower = H.v3_tick_to_price(lower_v3_tick, decimals0, decimals1)
    price_upper = H.v3_tick_to_price(upper_v3_tick, decimals0, decimals1)

    L = H.compute_liquidity_from_capital(v0_usd, price_entry, price_lower, price_upper)
    a0, a1 = position_amounts(price_entry, price_lower, price_upper, L)

    v_pos_entry = H.compute_position_value(price_entry, price_lower, price_upper, L)
    v_pos_exit = H.compute_position_value(price_exit, price_lower, price_upper, L)
    v_hodl_exit = a0 * price_exit + a1

    a0_exit, _ = position_amounts(price_exit, price_lower, price_upper, L)

    return CycleIL(
        cycle=cycle,
        mint_ts=str(mint_ts),
        burn_ts=str(burn_ts),
        lower_v3_tick=int(lower_v3_tick),
        upper_v3_tick=int(upper_v3_tick),
        price_lower=price_lower,
        price_upper=price_upper,
        price_entry=price_entry,
        price_exit=price_exit,
        v0_usd=v0_usd,
        liquidity=L,
        amount0_eth=a0,
        amount1_usdc=a1,
        v_position_exit=v_pos_exit,
        v_hodl_exit=v_hodl_exit,
        il_usd=v_pos_exit - v_hodl_exit,
        basket_delta_usd=v_hodl_exit - v_pos_entry,
        lp_value_change_usd=v_pos_exit - v_pos_entry,
        exited_range=not (price_lower <= price_exit <= price_upper),
        frac_eth_at_entry=(a0 * price_entry / v_pos_entry) if v_pos_entry > 0 else 0.0,
        frac_eth_at_exit=(a0_exit * price_exit / v_pos_exit) if v_pos_exit > 0 else 0.0,
    )


def ledger_totals(cycles: list[CycleIL]) -> dict:
    return {
        "n_cycles": len(cycles),
        "il_usd": sum(c.il_usd for c in cycles),
        "basket_delta_usd": sum(c.basket_delta_usd for c in cycles),
        "lp_value_change_usd": sum(c.lp_value_change_usd for c in cycles),
        "n_cycles_exited_range": sum(1 for c in cycles if c.exited_range),
        "worst_cycle_il_usd": min((c.il_usd for c in cycles), default=0.0),
    }


def as_rows(cycles: list[CycleIL]) -> list[dict]:
    return [asdict(c) for c in cycles]
