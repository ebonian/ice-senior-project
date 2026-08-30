"""E005 candidate registry, width-arm mapping, and frozen window constants.

Everything venue-independent is imported frozen from E003/gate1 (envelope,
cost model, LP capital); this module adds only what varies per pool. The
pre-registered candidate set is the table in
`loop/experiments/E005-pool-screen.md` — four families, every screened-out
candidate recorded with its reason, never silently dropped.

Pool ADDRESSES are not written here: `discover.py` resolves each candidate via
the factory (`getPool`) and writes `out/candidates.json`; downstream stages
read that file, so the chain stays the single source for addresses.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

E005 = Path(__file__).resolve().parent
BMS = E005.parent
GATE1 = BMS / "gate1"
E003 = BMS / "e003"
for p in (str(GATE1), str(E003), str(E005)):
    if p not in sys.path:
        sys.path.insert(0, p)

import envelope as E003_ENV  # noqa: E402  (frozen: e003-2026-08-29)
from engine import cost_model as CM  # noqa: E402  (frozen: gate1-2026-08-29)

# --- frozen, inherited ------------------------------------------------------
ENVELOPE = E003_ENV.ENVELOPE
ENVELOPE_BY_NAME = E003_ENV.ENVELOPE_BY_NAME
LP_CAPITAL_USD = E003_ENV.LP_CAPITAL_USD          # 1015.0
HEDGE_EQUITY_USD = E003_ENV.HEDGE_EQUITY_USD      # 405.0
TOTAL_CAPITAL_USD = E003_ENV.TOTAL_CAPITAL_USD    # 1420.0
TARGET_USD_PER_DAY = E003_ENV.TARGET_USD_PER_DAY  # 0.3890
TX_PER_RECENTER = E003_ENV.TX_PER_RECENTER        # 4
COST_MODEL_VERSION = CM.COST_MODEL_VERSION
ENVELOPE_VERSION = E003_ENV.E003_ENVELOPE_VERSION

WINDOW_START = "2026-05-01"
WINDOW_END = "2026-08-28"      # exclusive — E003's exact window

# E003's month block ranges, reused verbatim so every pool is measured over
# the identical chain window (e003/data/swaps/<month>.blocks.json).
MONTH_BLOCKS = {
    "2026-05": (458085624, 468748167),
    "2026-06": (468748168, 479089705),
    "2026-07": (479089706, 489802913),
    "2026-08": (489802914, 499082672),
}

# --- chain constants --------------------------------------------------------
RPC_URL = "https://arb1.arbitrum.io/rpc"
FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984".lower()
TICK_SPACING_BY_FEE = {100: 1, 500: 10, 3000: 60, 10000: 200}

# Token addresses on Arbitrum One. `discover.py` verifies symbol()/decimals()
# on-chain before anything downstream uses them.
TOKENS = {
    "WETH":   ("0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", 18),
    "USDC":   ("0xaf88d065e77c8cC2239327C5EDb3A432268e5831", 6),
    "WBTC":   ("0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f", 8),
    "ARB":    ("0x912CE59144191C1204E64559FE8253a0e49E6548", 18),
    "wstETH": ("0x5979D7b546E38E414F7E9822514be443A4800529", 18),
    "weETH":  ("0x35751007a407ca6FEFfE80b3cB397736D2cf4dbe", 18),
}
STABLES = {"USDC"}

# HL perp coin per token. wstETH/weETH map to ETH by the pre-registered
# ETH-beta exception (near-static full-notional ETH short).
HL_COIN = {"WETH": "ETH", "WBTC": "BTC", "ARB": "ARB",
           "wstETH": "ETH", "weETH": "ETH"}
ETH_BETA_TOKENS = {"wstETH", "weETH"}

# Binance 1h USD mark per token (None -> 1.0 for stables; ETH-beta tokens use
# the pool-implied price x the quote's mark, so they need no own feed).
BINANCE_USD = {"WETH": "ETHUSDT", "WBTC": "BTCUSDT", "ARB": "ARBUSDT",
               "USDC": None}


@dataclass(frozen=True)
class Candidate:
    slug: str          # filesystem/report identity
    family: str        # F1..F4, or "control"
    tokenA: str        # unordered pair as pre-registered; chain decides 0/1
    tokenB: str
    fee: int           # uint24 fee tier

    @property
    def tick_spacing(self) -> int:
        return TICK_SPACING_BY_FEE[self.fee]


# The pre-registered set, in the pre-registered fetch priority F1 -> F3 -> F2
# -> F4 (abort criteria cut from the tail). Control first: it gates everything.
CANDIDATES = [
    Candidate("weth_usdc_0p05",   "control", "WETH", "USDC", 500),
    Candidate("weth_usdc_0p30",   "F1", "WETH", "USDC", 3000),
    Candidate("wsteth_weth_0p01", "F3", "wstETH", "WETH", 100),
    Candidate("weeth_weth_0p01",  "F3", "weETH", "WETH", 100),
    Candidate("wbtc_weth_0p05",   "F2", "WBTC", "WETH", 500),
    Candidate("wbtc_weth_0p30",   "F2", "WBTC", "WETH", 3000),
    Candidate("arb_weth_0p05",    "F4", "ARB", "WETH", 500),
    Candidate("arb_weth_0p30",    "F4", "ARB", "WETH", 3000),
]

# F4 discovery shortlist: tokens with a live HL perp and an Arbitrum ERC20.
# The pre-registered rule is "top V3 Arbitrum pools by swap count over the
# window among tokens with a live HL perp"; a full-chain scan is not reachable
# on the public RPC, so the practical reading is this shortlist x {WETH, USDC}
# x {0.05%, 0.30%}, ranked by sampled swap counts. The narrowing is recorded
# as a deviation in the report.
DISCOVERY_TOKENS = {
    "LINK":   ("0xf97f4df75117a78c1A5a0DBb814Af92458539FB4", 18),
    "UNI":    ("0xFa7F8980b0f1E64A2062791cc3b0871572f1F7f0", 18),
    "GMX":    ("0xfc5A1A6EB076a2C7aD06eD22C90d7E710E35ad0a", 18),
    "PENDLE": ("0x0c880f6761F1af8d9Aa9C466984b80DAb9a8c9e8", 18),
    "CRV":    ("0x11cDb42B0EB46D95f990BeDD4695A6e3fA034978", 18),
    "AAVE":   ("0xba5DdD1f9d7F570dc94a51479a000E3BCE967196", 18),
    "LDO":    ("0x13Ad51ed4F1B7e9Dc168d8a00cB3f4dDD85EfA60", 18),
}

MIN_MEDIAN_SWAPS_PER_DAY = 48       # eligibility gate, pre-registered

# --- width arms -------------------------------------------------------------
# Pre-registered percentage arms, mapped to each pool's tickSpacing. The
# mapping keeps E003's convention (center snapped down to a spacing multiple,
# half-width a whole number of spacings) and reproduces E003's W10/W40/W160
# exactly on spacing 10: +-0.5% -> +-50 ticks, +-2.0% -> +-200, +-8.3% -> +-800.
ARM_PCTS = (0.001, 0.002, 0.005, 0.020, 0.083)


def arm_half_ticks(pct: float, tick_spacing: int) -> int:
    """Half-width in v3 ticks: the nearest whole multiple of tickSpacing to
    ln(1+pct)/ln(1.0001), floored at one spacing."""
    target = math.log(1.0 + pct) / math.log(1.0001)
    n = max(1, round(target / tick_spacing))
    return n * tick_spacing


def arms_for_spacing(tick_spacing: int) -> list[dict]:
    """Deduplicated arm list. On coarse spacings several percentage arms can
    map to the same tick width; they run once under a merged label."""
    by_half: dict[int, list[float]] = {}
    for pct in ARM_PCTS:
        by_half.setdefault(arm_half_ticks(pct, tick_spacing), []).append(pct)
    out = []
    for half in sorted(by_half):
        pcts = by_half[half]
        out.append({
            "label": "arm_" + "_".join(f"{p * 100:g}pct" for p in pcts),
            "target_pcts": pcts,
            "half_ticks": half,
            "actual_pct": 1.0001 ** half - 1.0,
        })
    return out
