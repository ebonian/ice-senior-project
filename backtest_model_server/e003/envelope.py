"""The three-point hedge-execution envelope, and the width-arm definitions.

WHY AN ENVELOPE. The hedge leg's fills cannot be predicted: there is no
historical L2 book, so maker fill probability and queue position are
unsimulatable (bot `analysis/strategy-review/04-backtest-design.md` §4.5). The
design doc's rule is that every hedge-leg result is three numbers, never one,
and that a change is actionable only if it wins under the pessimistic point.
E003 therefore prices the hedge as a cost envelope around a hedge ratio that is
NOT varied — the short always tracks the LP position's ETH delta.

WHERE EACH NUMBER COMES FROM. The fee schedule is frozen in
`gate1/engine/cost_model.py` (version `gate1-2026-08-29`) and is used unchanged.
Everything else is a pre-registered reading of measurements already published:

  maker/taker fee      1.44 / 4.32 bps   cost_model.HPL_MAKER_BPS/HPL_TAKER_BPS
                                         (published schedule, confirmed exactly
                                         in the T5 fill histogram)
  central maker share  64.63%            E002 finding F5 — NOTIONAL-weighted, the
                                         T5 figure. The count-weighted 86.06% is
                                         the trap F5 exists to prevent; using it
                                         understates HPL fees by 25%.
  optimistic / pessimistic maker share
                       95% / 0%          04-backtest-design.md §4.5 ("maker 95%"
                                         optimistic; "every rebalance-adjacent
                                         fill forced to taker" pessimistic, which
                                         for an always-in rule whose every hedge
                                         trade IS rebalance-adjacent means 0%).
  slippage             0.4 / 0.9 / 2.0 bps
                                         §4.5. Consistent with §4.3's de-biased
                                         all-fill measurement of +0.79 bps (T4)
                                         and +0.89 bps (T5) against HPL's own
                                         mid, which brackets the central 0.9.
  chase allowance      0 / 0 / +2.0 bps  §4.5's pessimistic "burst premium". The
                                         burst premium is UNRESOLVED in sign
                                         (T4 -0.32 bps, T5 +1.82 bps), so it is
                                         used only as a pessimistic bound and
                                         never as a central estimate.

CHANGING ANY OF THESE AFTER SEEING RESULTS INVALIDATES THE RUN
(04-backtest-design.md §6.3 guard 2, restated in the E003 pre-registration).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

GATE1 = Path(__file__).resolve().parent.parent / "gate1"
if str(GATE1) not in sys.path:
    sys.path.insert(0, str(GATE1))
from engine import cost_model as CM  # noqa: E402

E003_ENVELOPE_VERSION = "e003-2026-08-29"


@dataclass(frozen=True)
class EnvelopePoint:
    name: str
    maker_share_notional: float
    slippage_bps: float
    chase_bps: float

    @property
    def fee_bps(self) -> float:
        m = self.maker_share_notional
        return m * CM.HPL_MAKER_BPS + (1.0 - m) * CM.HPL_TAKER_BPS

    @property
    def total_bps(self) -> float:
        """All-in cost charged against each unit of rehedge notional."""
        return self.fee_bps + self.slippage_bps + self.chase_bps

    def cost(self, notional_usd: float) -> float:
        return notional_usd * self.total_bps / 1e4


ENVELOPE = (
    EnvelopePoint("optimistic",  0.9500, 0.4, 0.0),
    EnvelopePoint("central",     0.6463, 0.9, 0.0),
    EnvelopePoint("pessimistic", 0.0000, 2.0, 2.0),
)
ENVELOPE_BY_NAME = {p.name: p for p in ENVELOPE}


# --- width arms -----------------------------------------------------------
# The mapping is the harness's own, not a new invention:
#   03_run_infer_backtest.py:226-236  compute_lp_range_from_width
#     center_tick      = (tick // tick_spacing) * tick_spacing
#     half_width_ticks = width * tick_spacing // 2
# with tick_spacing = 10 for ETH/USDC 0.05%. Applied to the pool's v3 tick,
# because that is the tick the pool aligns to and the tick the live bot minted
# on: T5 cycle 6 minted -198970..-198870, a 100-tick interval = +-50 = W10.
# So W_N spans N tick-spacings in total, +-5N ticks, i.e. +-(1.0001^(5N) - 1).
TICK_SPACING = 10
WIDTH_ARMS = (4, 6, 10, 20, 40, 80, 160)


def half_width_ticks(width: int, tick_spacing: int = TICK_SPACING) -> int:
    return int(width) * int(tick_spacing) // 2


def width_pct(width: int, tick_spacing: int = TICK_SPACING) -> float:
    """+-% from center, as a fraction (W10 -> 0.005013)."""
    return 1.0001 ** half_width_ticks(width, tick_spacing) - 1.0


# --- capital ---------------------------------------------------------------
# bot docs/reference/parameters.md: "~$1,420 total - ~$1,015 LP, ~$405 hedge
# equity". Only the LP leg earns fees; the hedge equity is collateral. The
# $0.39/day target in the pre-registration is 10% APR on the $1,420 TOTAL
# (1420 * 0.10 / 365 = $0.3890), so the bar is set against total capital while
# only $1,015 of it is productive. That is the live configuration, and it is
# the conservative reading: putting all $1,420 into the LP would leave the perp
# short with no margin.
LP_CAPITAL_USD = 1015.0
HEDGE_EQUITY_USD = 405.0
TOTAL_CAPITAL_USD = LP_CAPITAL_USD + HEDGE_EQUITY_USD
TARGET_APR = 0.10
TARGET_USD_PER_DAY = TOTAL_CAPITAL_USD * TARGET_APR / 365.0   # $0.3890

# On-chain transaction count charged to one recenter. The pre-registration says
# "3-4 txs per REBALANCE"; 4 is the pessimistic end (burn+collect, swap-to-ratio,
# mint, dust sweep). Gas is $0.0101/tx so the choice moves $0.01 per recenter —
# the swap term at 5.155 bps of the swapped notional dominates it by ~25x.
TX_PER_RECENTER = 4
