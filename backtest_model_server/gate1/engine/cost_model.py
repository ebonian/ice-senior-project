"""Cost model for the delta-hedged concentrated-liquidity strategy.

SOURCE OF TRUTH: research/backtest_model_server/gate1/engine/cost_model.py
Deliberately self-contained (stdlib only, no repo imports) so it can be copied
into bot/analysis/ verbatim — see bot analysis/strategy-review/04-backtest-design.md
§2.3. If you change a constant here, change it in both copies and re-run
tests/test_cost_model_fixture.py.

CONSTANTS ARE FROZEN AS OF GATE 1 (2026-08-29). Changing one after seeing a
counterfactual result invalidates that result (§6.3 guard 2).

Every value below is measured, not assumed:

  On-chain (T5 `output/data/onchain_audit.json`: 43 txs, 23 pool swaps,
  $9,062.15 swap volume, $4.672 slippage, $0.433 gas, $0.029 failed-tx):
    - 4.672 / 9062 = 5.155 bps against a 5.0 bps fee tier. The measured
      "slippage" IS the pool fee plus 0.155 bps of everything else.
    - gas 0.433 / 43 = $0.0101 per tx.
    - 3-4 txs per REBALANCE, 2 per EXIT; 16 executed actions -> $0.319/action.

  Hyperliquid (published schedule, confirmed exactly in T4/T5 fill data — the
  T5 in-window fee-rate histogram is {1.44 bps: 348 fills, 4.32 bps: 57}):
    - maker 1.44 bps, taker 4.32 bps.

  Funding: never modelled. Replayed from recorded hourly rates.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- frozen constants ------------------------------------------------------
POOL_FEE_BPS = 5.0            # 0.05% tier; the dominant on-chain swap cost

# Fraction of the swap fee that reaches LPs rather than the Uniswap treasury.
# `slot0().feeProtocol` on this pool is 0x44 — a denominator of 4 on both
# tokens — so the protocol takes 1/4 and LPs keep 3/4. Verified on-chain, and
# no `SetFeeProtocol` event fires in blocks 460M-465M, which brackets both
# trial windows. This term is absent from the harness and from the training
# environment, which is why both overstate LP fee income by 1/0.75 = 33.3%.
# A swapper still PAYS the full 5 bps, so this scales fee income only, never
# `onchain_cost` below.
FEE_PROTOCOL_DENOMINATOR = 4
LP_FEE_SHARE = 1.0 - 1.0 / FEE_PROTOCOL_DENOMINATOR   # 0.75
EFFECTIVE_LP_FEE_BPS = POOL_FEE_BPS * LP_FEE_SHARE    # 3.75 bps to LPs

EXTRA_SWAP_SLIPPAGE_BPS = 0.155   # measured residual over the fee tier (T5)
GAS_USD_PER_TX = 0.0101       # $0.433 / 43 txs (T5, Arbitrum ~0.020 gwei)
TX_PER_REBALANCE = 3          # swap-to-ratio -> mint -> dust sweep
TX_PER_EXIT = 2               # burn+collect multicall -> swap-back
FAILED_MINT_RATE = 0.19       # 19% first-try mint failure (T5)

HPL_MAKER_BPS = 1.44
HPL_TAKER_BPS = 4.32

COST_MODEL_VERSION = "gate1-2026-08-29"


# --- on-chain --------------------------------------------------------------
@dataclass
class OnchainCost:
    swap_cost_usd: float
    gas_usd: float
    failed_tx_usd: float
    total_usd: float
    n_tx: int
    swapped_notional_usd: float


def onchain_cost(
    swapped_notional_usd: float,
    n_rebalances: int,
    n_exits: int,
    n_tx: int | None = None,
    failed_mint_rate: float = FAILED_MINT_RATE,
) -> OnchainCost:
    """On-chain cost of a set of LP actions.

    `swapped_notional_usd` is a policy output, not a constant: with
    `enable_exit_swap_back = true` and `asymmetric_mint_enabled = false` every
    cycle swaps to 100% USDC on EXIT and back on REBALANCE. Issues 8 and 9 are
    exactly the levers that change this term.

    `n_tx` overrides the 3-per-rebalance / 2-per-exit estimate when the real tx
    count is known (an audited trial). Count transactions, not log rows.
    """
    if n_tx is None:
        n_tx = n_rebalances * TX_PER_REBALANCE + n_exits * TX_PER_EXIT
    swap = swapped_notional_usd * (POOL_FEE_BPS + EXTRA_SWAP_SLIPPAGE_BPS) / 1e4
    gas = n_tx * GAS_USD_PER_TX
    failed = n_rebalances * failed_mint_rate * GAS_USD_PER_TX
    return OnchainCost(swap, gas, failed, swap + gas + failed, n_tx, swapped_notional_usd)


# --- Hyperliquid execution -------------------------------------------------
def hpl_fee(notional_usd: float, is_maker: bool) -> float:
    return notional_usd * (HPL_MAKER_BPS if is_maker else HPL_TAKER_BPS) / 1e4


def hpl_fees_from_fills(fills: list[tuple[float, bool]]) -> float:
    """`fills` = [(notional_usd, is_maker), ...]."""
    return sum(hpl_fee(n, m) for n, m in fills)


def hpl_fees_from_shares(
    maker_notional_usd: float, taker_notional_usd: float
) -> float:
    """Aggregate form the counterfactuals use.

    Note the weighting trap this exists to make explicit: the maker share that
    drives the fee line is NOTIONAL-weighted, not fill-count-weighted. In T5 the
    two are 64.6% and 86.1% — using the count-weighted figure understates HPL
    fees by 25%, because the taker fills are the large ones.
    """
    return (
        maker_notional_usd * HPL_MAKER_BPS + taker_notional_usd * HPL_TAKER_BPS
    ) / 1e4


# --- funding ---------------------------------------------------------------
def funding_pnl(hourly_rates: list[tuple], notional_path) -> float:
    """funding = sum over hours of rate(h) x signed perp notional(h).

    Sign convention: a positive hourly rate means longs pay shorts, so a short
    position RECEIVES. `notional_path(hour)` returns the absolute perp notional;
    the strategy is short-biased, so income is positive. Never modelled as a
    constant and never abs()'d — every measured window received funding.
    """
    total = 0.0
    for hour, rate in hourly_rates:
        n = notional_path(hour)
        if n:
            total += rate * n
    return total
